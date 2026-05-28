# Research Brief — notebook-preamble-recovery-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-27T23:59:00Z

---

## In-codebase context

### Design notes that apply

**`04-parsing-and-chunking.md` Rule 2 (verbatim):**
> "Extract `\newcommand` definitions and 'throughout this paper, $X$ denotes...' prose from the
> introduction. Prepend this as a header to every chunk from the paper before embedding. **This is
> the single biggest retrieval-quality lever after macro expansion.** Two papers using `X` to mean
> different things now embed differently because their preambles differ."

The scan brief (`preamble-without-raw-tex-2026-05-27.md`) provides an empirical qualification:
on the ar5iv path, LaTeXML has already resolved every `\newcommand` into MathML `alttext`. So
for **dense retrieval** preamble is largely cosmetic on the ar5iv path. The one load-bearing
consumer remaining is `get_definitions` — the `index_definitions.py` pipeline reads
`load_preamble(paper_id)` and produces zero definition rows when `preamble.json` is absent.

**`07-multi-agent-caching.md` (BP1 / tool-schema stability):** This milestone adds no MCP tool
and changes no tool schema. `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` are both
explicitly out of scope (AC X-1 / X-2). No re-pin needed.

### Codebase gap: actual scope of the problem

Live measurement (2026-05-27):

- `var/arxmcp/corpus/parsed/`: **137 papers** with `index.html`
- `var/arxmcp/corpus/raw/`: **0 directories** (all ar5iv-only)
- `var/arxmcp/corpus/preamble/`: **0 directories** (zero `preamble.json` files anywhere)
- `var/arxmcp/ops/parser-failures/preamble.log`: 6260 lines, 142 unique paper IDs, ALL with
  message `raw .tex source not found at .../corpus/raw/<id>; run tools/fetch_seed.py first`

**The back-fill scope is 137 papers, not ~65.** The milestone brief and scan brief cite "~65 in
the live notebook tree." The preamble.log contains 142 unique IDs (including some that appeared
multiple times from repeated re-embed runs). The `corpus/parsed/` tree has 137 papers, all
missing raw tex. The implementer should target all 137 in `ingest-recover-preambles`, not just
notebook-ingest-path papers.

### `fetch_eprint` return contract (verbatim from `tools/arxiv_fetch.py:234-297`)

```python
def fetch_eprint(
    paper_id: str,
    raw_dir: Path,                    # NOTE: receives the PARENT dir; appends paper_id internally
    contact_email: str | None = None,
    timeout: float = 60.0,
    ssl_context: ssl.SSLContext | None = None,
) -> FetchResult:
    ...
    raw_dir = raw_dir / paper_id      # ← function mutates local variable to paper-specific dir
    raw_dir.mkdir(parents=True, exist_ok=True)
```

The function **creates the `raw_dir / paper_id` subdirectory** itself. The `_extract_eprint_response`
call within writes either a tar-extracted set of files or a single `.tex` file into that directory.
The returned `FetchResult.raw_dir` is the paper-scoped directory (e.g.
`var/arxmcp/corpus/raw/2307.00001/`). **Do not pre-create the directory** — `fetch_eprint`
handles that atomically.

**Tarball format:** arXiv `/e-print/` responses are gzip-compressed; body is either a tar archive
(multi-file) or bare `.tex` (single-file). `_extract_eprint_response` tries `tarfile.open` first
and falls back to bare-tex on `TarError`. The `_safe_extract` helper in `tools/arxiv_fetch.py:330`
already enforces path-traversal protection (Threat 1) via `relative_to` check.

**Error contract:** raises `urllib.error.HTTPError` on non-2xx (callers must catch). Does NOT
enforce the politeness sleep — caller is responsible per the docstring:
> "Caller is responsible for the politeness sleep BEFORE invoking this — the function does not
> enforce inter-call spacing."

**100 MB Threat-7 cap:** already enforced inside `fetch_eprint` at lines 268-284.

**`ARXMCP_CONTACT_EMAIL` enforcement:** `build_user_agent` (called inside `fetch_eprint`)
raises `RuntimeError` if neither `contact_email` arg nor `ARXMCP_CONTACT_EMAIL` env var is set.
This propagates immediately. The `notebook_fetch.py` currently has NO reference to
`ARXMCP_CONTACT_EMAIL`; it will fail loudly at the first `fetch_eprint` call if the env var
is unset — which IS the correct behavior per AC7, but currently undocumented.

### `ingest/preamble.py` — `extract_preamble` entry point

`extract_preamble(paper_id)` at line 313:

1. Calls `_validate_paper_id(paper_id)` — rejects non-arXiv-format IDs.
2. Constructs `raw_paper_dir = RAW_DIR / paper_id` where `RAW_DIR` = `var/arxmcp/corpus/raw`.
3. If `raw_paper_dir` doesn't exist: raises `FileNotFoundError` (caught by
   `PER_PAPER_FAILURE_EXCEPTIONS = (OSError, ValueError, FileNotFoundError)`).
4. Picks root `.tex` via `_select_root_tex` (top-level-first, falls back to recursive
   `find_main_tex`); enforces symlink + path-containment guard (Threat 1).
5. Writes output to `PREAMBLE_DIR / paper_id / "preamble.json"` where
   `PREAMBLE_DIR = var/arxmcp/corpus/preamble`.

**Idempotent:** `_read_existing_preamble` short-circuits on SHA256 match.

The `extract_preamble` function **raises** on failure; it does not swallow exceptions. The
`ingest/chunker.py:_resolve_preamble_doc` wrapper catches `PER_PAPER_FAILURE_EXCEPTIONS` and
returns `None` with a WARNING. The new `fetch_raw_tex_if_missing` helper in
`tools/_notebook_common.py` must similarly catch and log (not raise) on failure — the notebook
run must not abort (AC4).

### `notebook_fetch.py` — no preamble code exists today

Confirmed: zero references to `preamble`, `fetch_eprint`, `ARXMCP_CONTACT_EMAIL`, or `RAW_DIR`
in `tools/notebook_fetch.py`. No duplication risk. The module currently imports only from
`ingest.ar5iv_fetch`, `ingest.identifiers`, and `tools._notebook_common`.

### `_notebook_common.py` — no `CORPUS_RAW_DIR` constant

The module defines `CORPUS_PARSED_DIR`, `CORPUS_CHUNKS_DIR`, `CORPUS_EMBEDDINGS_DIR`. It has
NO `CORPUS_RAW_DIR`. The implementer must add one:
`CORPUS_RAW_DIR: Path = REPO_ROOT / "var" / "arxmcp" / "corpus" / "raw"`

This constant must also be patched in tests to redirect to `tmp_path`.

### Politeness sleep — no double-sleep risk

`notebook_fetch.py` manages its own `time.sleep(sleep_seconds)` after each ar5iv
network fetch. The 3-second sleep is per-request to `ar5iv.labs.arxiv.org`. The new
`fetch_eprint` call targets `export.arxiv.org` — a separate host. Per the scan brief:
> "The politeness sleep is per-request to `export.arxiv.org`, NOT shared with the ar5iv
> budget."

The helper must sleep 3 seconds BEFORE calling `fetch_eprint` (matching the pattern in
`fetch_seed.py::politeness_sleep`). Sleeping after the ar5iv network fetch and before the
eprint fetch avoids two consecutive network hits without a pause, but avoids double-sleeping
on local-cache hits (where the ar5iv step already skipped its sleep).

Recommended implementation: sleep once, before `fetch_eprint`, only when a real network eprint
fetch will occur (i.e., raw dir is absent). Use `time.sleep(sleep_seconds)` in the helper,
not the `politeness_sleep(start_time)` pattern (which needs a start reference).

### Test gaps

`tests/tools/test_notebook_scripts.py` has `test_fetch_happy_path`, `test_fetch_distinguishes_rate_limit_from_miss`, etc. — all mock `try_cache`, none mock `fetch_eprint`. The new tests must:

1. Mock `fetch_eprint` (patch at `tools.notebook_fetch.fetch_eprint` after the import).
2. Assert that `fetch_raw_tex_if_missing` is called after a `try_cache` hit.
3. Assert a 503 `HTTPError` from `fetch_eprint` does NOT raise in `notebook_fetch.run`.
4. Assert `CORPUS_RAW_DIR` is redirected to `tmp_path` (monkeypatch `notebook_fetch.CORPUS_RAW_DIR`).

Existing `test_fetch_happy_path` covers the local-cache-hit path; the new test should cover the
genuine-fetch path (`reason="ok"`) to verify `fetch_eprint` is invoked after a network ar5iv fetch.

### Makefile pattern for `ingest-recover-preambles`

Existing targets use `$(PYTHON) -m <module> $(ARGS)`. The new target should follow the same
pattern with a new script at `tools/recover_preambles.py` (not a module in `ingest/`). The
script walks `var/arxmcp/corpus/parsed/*/index.html`, identifies papers missing a
`preamble.json`, and calls `fetch_eprint` + `extract_preamble`. It must accept
`--notebook=<slug>` to scope to one notebook's papers (read from
`var/arxmcp/notebooks/<slug>/papers.txt`). Default is all parsed papers.

---

## Prior decisions and lessons

**From memory + git log:**

- `b489048` ("chore(ingest): quiet structural noise in re-embed logs") was the log-hygiene commit
  that quieted the `extract_preamble` ERROR+traceback to a WARNING for the `FileNotFoundError`
  case. This commit is already shipped. The `preamble.py` change is present in HEAD; the
  implementer does not need to re-apply it.

- The `tests/tools/test_notebook_scripts.py` fixture (`notebooks_base`, `corpus_dirs`) already
  monkeypatches `notebook_fetch.NOTEBOOKS_BASE` and `DEFAULT_PARSED_DIR`. The new
  `CORPUS_RAW_DIR` constant must be added to the same fixture, or a new `raw_dir` fixture must
  be added. **Check that `notebook_fetch.CORPUS_RAW_DIR` is the monkeypatch target** (not
  `_notebook_common.CORPUS_RAW_DIR`) if the constant is imported into `notebook_fetch`.

- The `embedder-truncation-m1` milestone confirmed 2778 tests pass. The test count floor for
  this milestone is 2778+ per AC X-3.

- **Textbook-ingest-m1** memory note: `_PAPER_ID_FULL_PATTERN` in identifiers.py uses `\Z`
  anchor. The `is_valid_arxiv_paper_id` function (used in `notebook_fetch.py:75`) only accepts
  new-style arXiv IDs. The new helper must likewise validate paper_id before calling
  `fetch_eprint` — but `fetch_eprint` itself calls `validate_paper_id` (PAPER_ID_RE check) at
  line 256, so double-validation is not harmful (it's a cheap regex).

---

## External sources

The arXiv `/e-print/` endpoint at `https://export.arxiv.org/e-print/<paper_id>` is already used
by `tools/fetch_seed.py`. The politeness contract (3-second inter-request sleep, User-Agent with
contact email, 503 Retry-After honor) is already proven and unit-tested via
`tests/test_arxiv_fetch.py`. No new external service is involved.

The scan brief cites the arXiv TOS §3 requirement for identifying User-Agent:
> "ARXMCP_CONTACT_EMAIL is required (arXiv TOS §3 — politeness contract). Export it in your
> shell before running any tool that hits arxiv.org."

No MCP spec implications — no tool surface change.

---

## Recommendation

**Implement Option A exactly as the scan brief and roadmap specify**, with one correction to the
back-fill scope: target **all 137 papers** in `corpus/parsed/` (not ~65), because every
ar5iv-only paper is missing raw tex regardless of how it was ingested.

**Implementation steps in order:**

1. Add `CORPUS_RAW_DIR: Path = REPO_ROOT / "var" / "arxmcp" / "corpus" / "raw"` to
   `tools/_notebook_common.py` and its `__all__`.

2. Add `fetch_raw_tex_if_missing(paper_id, raw_dir, sleep_seconds)` to
   `tools/_notebook_common.py`. It should: check if `raw_dir / paper_id` already exists and
   has at least one `.tex` file (idempotent skip); sleep `sleep_seconds`; call
   `fetch_eprint(paper_id, raw_dir)`; return `True` on success, `False` on any
   `urllib.error.HTTPError` / `OSError` / `RuntimeError` (the `PER_PAPER_FAILURE_EXCEPTIONS`
   envelope), logging a WARNING and appending to `preamble.log` with status "skip_eprint".

3. In `tools/notebook_fetch.py`: import `fetch_eprint` from `tools.arxiv_fetch` and
   `fetch_raw_tex_if_missing` from `tools._notebook_common`; call
   `fetch_raw_tex_if_missing(paper_id, CORPUS_RAW_DIR, sleep_seconds)` after any `result.hit`
   (both `"ok"` and `"ok_local_cache"`). Add to the summary line:
   `preamble_recovered=N preamble_failed=K`. Document `ARXMCP_CONTACT_EMAIL` requirement
   in the module docstring.

4. Add `tools/recover_preambles.py` with `--notebook=<slug>` flag; wire as
   `make ingest-recover-preambles` in the Makefile following the existing `$(PYTHON) -m ...`
   pattern.

5. Add tests to `tests/tools/test_notebook_scripts.py` covering: (a) `fetch_eprint` invoked
   after ar5iv hit; (b) 503 from `fetch_eprint` does not abort notebook run; (c) idempotent
   skip when raw dir already exists.

**On AC7 (ARXMCP_CONTACT_EMAIL required):** `fetch_eprint` already enforces this via
`build_user_agent`. No additional enforcement is needed in `notebook_fetch.py` beyond
documenting the requirement. The `RuntimeError` from `build_user_agent` will propagate through
`fetch_raw_tex_if_missing` and be caught as part of the failure envelope — meaning a missing
env var will produce `preamble_failed=N` for every paper, not a hard crash. If a hard-fail on
missing env var is desired at script startup (rather than per-paper), add an early check in
`notebook_fetch.run()` before the paper loop.

---

## Open questions

**Q1: Exact back-fill scope.**
Resolved empirically: 137 papers in `corpus/parsed/`, 0 in `corpus/raw/`. The milestone brief
says "~65 in the live notebook tree" but that was an estimate from notebook-only ingest. The
actual corpus has 137 papers total, all missing raw tex. The `ingest-recover-preambles` target
should walk all of `corpus/parsed/*/` by default, not just notebook-scoped papers.

**Q2: Idempotency design for `ingest-recover-preambles`.**
Recommend: check `(raw_dir / paper_id).exists() and any((raw_dir / paper_id).glob("*.tex"))`.
If the raw dir exists and has at least one `.tex`, skip the `fetch_eprint` call (idempotent).
Then call `extract_preamble(paper_id)` — it is already idempotent via SHA256 cache.

**Q3: Summary line format extension.**
Recommend extending the `notebook_fetch.py` summary line to:
`fetched=N from_cache=M missing=K rate_limited=R malformed=J preamble_recovered=P preamble_failed=F`
This mirrors the existing format and gives the operator visibility into the new step.

**Q4: AC5 chunk_id rotation — guard needed?**
No guard needed. The chunker's `_compute_chunk_id` is content-addressable: `arxiv:<id>:<sha256(preamble_text + body_text)[:16]>`. When preamble changes from empty to populated, the chunk_id changes. This is correct by design — LanceDB MVCC handles it cleanly. The scan brief explicitly confirms this:
> "No `corpus_version` ripple needed — the next `notebook_ingest` will pick up the now-populated
> `preamble.json` and re-chunk under a new chunk_id (because `_compute_chunk_id` is preamble-
> sensitive), which is exactly the LanceDB MVCC behavior the chunker already pins."

**Q5: AC7 hard-fail vs per-paper silent fail on missing ARXMCP_CONTACT_EMAIL.**
Recommend: check `os.environ.get("ARXMCP_CONTACT_EMAIL")` at the start of `notebook_fetch.run()`
and raise `NotebookError` immediately if absent. This gives a clear error message rather than
per-paper `preamble_failed` entries with a cryptic RuntimeError message buried in the log.

No other open questions — implementation can proceed on the above recommendation.

---

## External writes the implementation will require

The new `GET https://export.arxiv.org/e-print/<paper_id>` egress is the SAME endpoint already
used by `tools/fetch_seed.py`. It is a **read-only public endpoint** with a documented
politeness contract already implemented in `tools/arxiv_fetch.py`. Per project convention
(agent-conventions.md §8), a runtime egress to a documented public read-only endpoint respecting
politeness contracts is NOT a Phase-4-gateable external write.

**None** — this milestone is purely local. No git push, no PR, no infra mutation, no new
external endpoint, no ticket creation required as part of the implementation.
