# Research Brief — notebook-preamble-recovery-m1

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-28T00:55:00Z

---

## In-codebase context

### Design constitution relevance

**`04-parsing-and-chunking.md` Rule 2 (lines 83-89):**
> "Per-paper preamble prepended to every chunk. Extract `\newcommand` definitions
> and 'throughout this paper, $X$ denotes...' prose from the introduction. Prepend
> this as a header to every chunk from the paper before embedding. **This is the
> single biggest retrieval-quality lever after macro expansion.**"

The scan brief (`.claude/notes/scans/preamble-without-raw-tex-2026-05-27.md`) amends
this: on the ar5iv path, LaTeXML already inline-expands macros into MathML `alttext`,
so the preamble's practical value is **via `get_definitions`** rather than embedder
quality. This is a load-bearing qualification for the milestone's scope.

**`08-security-observability-ops.md` Threat 1 (path traversal):**
> "Mitigation: strict regex on every arxiv ID input: `^\d{4}\.\d{4,5}(v\d+)?$` for
> new-style IDs. Reject at the JSON-Schema level so it never reaches handlers."

The path `ingest/preamble.py:343-357` already implements the Threat-1 mitigation for
tarball contents — the `is_relative_to(resolved_root)` check at lines 350-357 is
load-bearing. Specifically:

```python
resolved_main = main_tex.resolve()
resolved_root = raw_paper_dir.resolve()
if (
    main_tex.is_symlink()
    or not resolved_main.is_relative_to(resolved_root)
):
    raise ValueError(...)
```

This guards against the tarball-bomb / path-traversal symlink attack (see Failure
Mode 1 below). The `_safe_extract` in `tools/arxiv_fetch.py:330-346` adds a second
layer at extraction time.

**`08-security-observability-ops.md` Threat 7 (source ingestion fetches):**
> "Content-length sanity checks (a single paper > 100 MB source is suspicious)."

`tools/arxiv_fetch.py:70`: `MAX_RESPONSE_BYTES = 100 * 1024 * 1024` — enforced at
two points in `fetch_eprint`: (1) pre-read Content-Length check lines 268-278, (2)
post-read length check line 280. Both already in place.

**`03-ingestion-pipeline.md` Source 3:**
> "Rate limit: 1 request per 3 seconds per IP, with explicit guidance to back off on
> 503. Hard ceiling."

`tools/arxiv_fetch.py:35`: `POLITENESS_SLEEP_SECONDS = 3.0`. The `fetch_eprint`
function's docstring explicitly states: "Caller is responsible for the politeness
sleep BEFORE invoking this — the function does not enforce inter-call spacing."
**The `fetch_raw_tex_if_missing` helper MUST call `politeness_sleep` (or equivalent)
before each `fetch_eprint` call.** This is not enforced internally by `fetch_eprint`.

### Key codebase facts

**`fetch_eprint` call contract (tools/arxiv_fetch.py:234-297):**
- Signature: `fetch_eprint(paper_id, raw_dir, contact_email=None, timeout=60.0, ssl_context=None) -> FetchResult`
- The `raw_dir` argument is `var/arxmcp/corpus/raw` (NOT `var/arxmcp/corpus/raw/<paper_id>/`). `fetch_eprint` internally appends `/ paper_id` at line 257: `raw_dir = raw_dir / paper_id`.
- Raises `urllib.error.HTTPError` for non-2xx. 404 (withdrawn paper) and 503 (rate limit) both surface as `HTTPError` with `e.code`.
- Does NOT sleep internally — caller must sleep.

**`_safe_extract` (tools/arxiv_fetch.py:330-346):** Pre-checks all tarball member paths against `dest.resolve()` using `relative_to`. Raises `RuntimeError` (not `TarError`) on path-traversal detection. This means the `PER_PAPER_FAILURE_EXCEPTIONS` envelope in `fetch_seed.py` (which catches `RuntimeError`) correctly swallows tarball-bomb failures. The new `fetch_raw_tex_if_missing` helper should catch the same tuple.

**`ingest/preamble.py` `PER_PAPER_FAILURE_EXCEPTIONS`:** Only `(OSError, ValueError, FileNotFoundError)` — does NOT include `RuntimeError`. If `_safe_extract` raises `RuntimeError` from a path-traversal attempt on a paper's tarball, `extract_preamble` will propagate it rather than catching it. This is intentional (it is a security event, not a recoverable per-paper failure). The `fetch_raw_tex_if_missing` helper should catch `RuntimeError` at the fetch layer and log it as an extraction failure — **do not allow it to propagate to the notebook run loop**.

**`_notebook_common.py` missing `CORPUS_RAW_DIR` constant:** The module defines `CORPUS_PARSED_DIR`, `CORPUS_CHUNKS_DIR`, `CORPUS_EMBEDDINGS_DIR` — but NOT `CORPUS_RAW_DIR`. The new `fetch_raw_tex_if_missing` helper needs `var/arxmcp/corpus/raw` and must define this path consistently. Add `CORPUS_RAW_DIR` to `_notebook_common.py` (mirrors the pattern), then monkeypatch it in tests.

**`ARXMCP_CONTACT_EMAIL` enforcement:** `build_user_agent()` in `tools/arxiv_fetch.py:94-107` raises `RuntimeError` (not at import time — at call time). This means the enforcement is lazy: a test that patches `urlopen` will not trigger the error unless it also calls through to `build_user_agent`. The test pattern used across the codebase (e.g. `test_arxiv_fetch.py`, `test_graph_ingest.py`) is `monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")`. **AC7 must NOT add import-time enforcement** — doing so would break every test that imports from `tools/notebook_fetch.py` without setting the env var.

**Existing test file for notebook_fetch:** `tests/tools/test_notebook_scripts.py` contains all `notebook_fetch` tests. There is NO separate `tests/test_notebook_fetch.py`. New tests for this milestone go into `tests/tools/test_notebook_scripts.py`. The fixture pattern uses `monkeypatch.setattr(notebook_fetch, "try_cache", _mock)` — the new `fetch_eprint` call should be similarly patched.

---

## Prior decisions and lessons

**Recent git log:** The immediately prior milestone is `b489048 chore(ingest): quiet structural noise in re-embed logs` which demoted preamble errors to warnings. This milestone restores correctness rather than silencing symptoms.

**`embedder-truncation-m1` state:** Complete. Re-embed ran successfully. The ~65-paper back-fill scope from the scan brief reflects the state AFTER that re-embed.

**Politeness sleep ownership:** The `fetch_eprint` function deliberately does NOT sleep internally. The scan brief note 4 explicitly: "The politeness sleep is per-request to `export.arxiv.org`, NOT shared with the ar5iv budget. Sleep budgets compose additively; make sure the helper doesn't double-sleep." The `notebook_fetch.run()` loop sleeps AFTER each `try_cache` network fetch (line 106). The new `fetch_raw_tex_if_missing` call must add its own 3-second sleep — bringing the per-paper cost from ~3s to ~6s for papers that need a raw-tex fetch.

**Chunk_id rotation warning:** After back-fill + next re-embed, papers that had `preamble_ref=null` will now have a non-null `preamble_ref`, which changes `sha256(preamble_text + body_text)[:16]` and thus all `chunk_id`s for those papers. For ~65 papers, this will produce re_embedded≫copied in the re-embed summary — 2-4 hours additional CPU. The operator must be warned in the implementation summary.

**Doc-placement for implementation summary:** Prior E13 milestones place audit docs at `.claude/docs/security-threat-N-audit.md`. Any implementation summary for this milestone goes to `.claude/notes/milestones/notebook-preamble-recovery-m1/implementation-summary.md`.

---

## External sources

### arXiv API Terms of Use (fetched 2026-05-28)

Verbatim rate limit clause from `https://info.arxiv.org/help/api/tou.html`:
> "When using the legacy APIs (including OAI-PMH, RSS, and the arXiv API), make no
> more than one request every three seconds, and limit requests to a single
> connection at a time."

Additional constraint: "Attempt to circumvent rate limits" is explicitly prohibited.
The terms apply collectively across all machines under the operator's control — not
per-machine. For a back-fill of ~65 papers at 3 s/paper ≈ 3.25 minutes total wall
time: this is well within the envelope. The `fetch_eprint` endpoint is not the API
endpoint, but the same politeness contract applies.

### arXiv user-manual (fetched 2026-05-28)

From `https://info.arxiv.org/help/api/user-manual.html`:
> "In cases where the API needs to be called multiple times in a row, we encourage
> you to play nice and incorporate a 3 second delay in your code."

The User-Agent requirement is project-defined (not mandated verbatim in public docs)
but the existing `ARXMCP_USER_AGENT_TEMPLATE = "arXMCP/0.1 (mailto:{email})"` in
`tools/arxiv_fetch.py:33` matches the de-facto arXiv convention and is already
enforced by `build_user_agent()`.

### No new external dependencies

This milestone reuses `tools.arxiv_fetch.fetch_eprint` — the same endpoint
(`export.arxiv.org`) and transport already used by `tools/fetch_seed.py`. No new
vendor docs, no new TLS certificates, no new rate-limit envelope.

---

## Failure mode analysis

### FM-1: Tarball bomb (path-traversal symlink)

**Trigger:** A malicious or corrupt arXiv tarball contains a member with path
`paper.tex -> /etc/passwd` or `../../evil` that escapes the paper's `raw_dir`.

**Observable symptom:** `_safe_extract` (tools/arxiv_fetch.py:330-346) raises
`RuntimeError("refusing to extract path outside dest: ...")`. Because `RuntimeError`
is NOT in `ingest/preamble.py::PER_PAPER_FAILURE_EXCEPTIONS`, it would propagate
past `extract_preamble`. The `fetch_raw_tex_if_missing` helper must catch it.

**Mitigation:** `_safe_extract` already uses `member_path.relative_to(dest_resolved)`,
which collapses symlinks via `.resolve()` before comparison. The `preamble.py:350-357`
`is_relative_to` check provides a second layer after extraction. Both are load-bearing.
The `fetch_raw_tex_if_missing` helper should catch `RuntimeError` in addition to the
`fetch_seed.py` `PER_PAPER_FAILURE_EXCEPTIONS` tuple, log at ERROR level (not WARNING
— this is a security event), and return `False` without aborting the notebook run.

### FM-2: arXiv 429 / 503 during back-fill

**Trigger:** Back-fill of 65 papers at 3 s/paper takes ~3 minutes. If arXiv's load
balancer issues a 503 mid-run, the current `fetch_eprint` raises `HTTPError(503)`.

**Observable symptom:** Without 503 backoff in `fetch_raw_tex_if_missing`, the first
503 aborts the remaining 40+ papers. The back-fill log shows
`preamble_recovered=N rate_limited=0 skipped=40+`.

**Mitigation:** `fetch_raw_tex_if_missing` must implement the same 503 backoff pattern
as `fetch_seed.py::fetch_with_backoff`: honor `Retry-After` header via
`parse_retry_after`, cap at `MAX_503_BACKOFF_SECONDS`, log the wait, then retry. For
the back-fill script (where there is no notebook loop to return to), 503 should retry
with exponential backoff; for the per-paper inline call in `notebook_fetch`, a single
503 should log and return `False` (the operator will re-run).

### FM-3: Withdrawn paper (ar5iv hit + e-print 404 asymmetry)

**Trigger:** A paper that was indexed by ar5iv before withdrawal returns 200 from
ar5iv (HTML cached) but 404 from `/e-print/<id>` (paper withdrawn, tarball removed).

**Observable symptom:** `fetch_eprint` raises `urllib.error.HTTPError(404)`. Without
handling, this propagates to the notebook loop.

**Mitigation:** `fetch_raw_tex_if_missing` must treat `HTTPError(404)` as a
non-recoverable per-paper miss, log to `preamble.log` with reason `"withdrawn_404"`,
and return `False`. This is AC4 — the notebook run continues. The paper stays in
`papers.txt`; its ar5iv HTML is still usable for chunking (just no preamble).

**NOTE:** The design constitution's `03-ingestion-pipeline.md` does NOT document this
asymmetry — it is a gap in the design notes, not a conflict.

### FM-4: `extract_preamble` raises on malformed `.tex`

**Trigger:** A paper's `.tex` has malformed LaTeX (e.g. unclosed brace, binary
garbage in the file). `extract_preamble`'s regex scans may raise `UnicodeDecodeError`
(caught by `OSError`) or `ValueError` from `_select_root_tex`.

**Mitigation:** `ingest/preamble.py::PER_PAPER_FAILURE_EXCEPTIONS = (OSError, ValueError,
FileNotFoundError)` already catches these. `extract_preamble` logs the exception at
WARNING (for `FileNotFoundError`) or ERROR (for all others) and returns `None`. The
`fetch_raw_tex_if_missing` helper calls `extract_preamble` after a successful fetch;
since `extract_preamble` already catches its own exceptions, the helper only needs to
handle the `fetch_eprint`-side failures. No double-catch risk.

### FM-5: Concurrent `make ingest-recover-preambles` runs

**Trigger:** Two operator terminals both run `make ingest-recover-preambles`
simultaneously, both writing to `var/arxmcp/corpus/raw/<paper_id>/`.

**Observable symptom:** `fetch_eprint` calls `raw_dir.mkdir(parents=True, exist_ok=True)`
at line 258 — this is atomic on POSIX (mkdir is O_CREAT | O_EXCL internally when the
dir doesn't exist, and `exist_ok=True` makes it idempotent). If both processes write
the same paper concurrently, they both write to `<paper_id>/` and may overwrite each
other's files. For `.tex` extraction, this is benign — the content is identical (same
paper from arXiv). For `extract_preamble`'s JSON output, the write is to a temp file
followed by rename (Python's `Path.write_text` is NOT atomic). Risk is very low in
practice (single-developer workstation) but worth noting.

**Mitigation:** Document "run one back-fill at a time" in the `make` target help text.
No locking mechanism is warranted for this project.

### FM-6: `ARXMCP_CONTACT_EMAIL` regression in tests

**Trigger:** AC7 enforcement is implemented at import time or module-level (e.g. reading
`os.environ["ARXMCP_CONTACT_EMAIL"]` at module load in `notebook_fetch.py`) rather than
at call time.

**Observable symptom:** Every test that imports from `tools.notebook_fetch` fails with
`KeyError` or `RuntimeError` unless `ARXMCP_CONTACT_EMAIL` is set in the environment.
The existing test suite in `tests/tools/test_notebook_scripts.py` does NOT set this
env var (it only patches `try_cache` and `run_bulk_ingest`).

**Mitigation:** `build_user_agent()` already enforces `ARXMCP_CONTACT_EMAIL` lazily
(at call time, not import time — see `tools/arxiv_fetch.py:94-107`). The
`fetch_raw_tex_if_missing` helper should pass `contact_email=None` to `fetch_eprint`
(which then calls `build_user_agent()` at call time). Tests that cover the raw-tex
fetch path must use `monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")`.
Tests that only exercise the ar5iv-cache path (patching `try_cache`) need no change.

### FM-7: Chunk_id rotation surprise after back-fill

**Trigger:** Operator runs `make ingest-recover-preambles`, then triggers `make
re-embed-all` expecting a quick update — instead sees ~65× re-embed operations.

**Observable symptom:** `re_embed.py` logs `re_embedded=N copied=M` where N≫M for the
notebook. The re-embed run takes 2-4 additional hours beyond the operator's expectation.

**Mitigation:** This is INTENDED behavior (AC5) but must be warned about explicitly. The
implementation summary should contain a "operator note: chunk_ids will rotate for all
back-filled papers on the next re-embed run." The Makefile target help text should
also warn about this.

---

## Recommendation

Implement `fetch_raw_tex_if_missing(paper_id, raw_dir, contact_email=None)` in
`tools/_notebook_common.py`, not in a new file. This keeps the helper co-located with
the other shared notebook infrastructure and maintains the monkeypatch pattern already
established in `tests/tools/test_notebook_scripts.py`.

The helper signature:
- Returns `True` on success (raw `.tex` written to `raw_dir / paper_id`).
- Returns `False` on any per-paper failure (404, 503, tarball bomb, malformed tex).
- Catches: `urllib.error.HTTPError`, `RuntimeError`, `OSError`, `tarfile.TarError`,
  `gzip.BadGzipFile` (the full `fetch_seed.py` envelope minus `subprocess.TimeoutExpired`
  which does not apply here since no LaTeXML is invoked).
- Skips (returns `True` with no fetch) if `raw_dir / paper_id` already exists and
  contains at least one `.tex` file — idempotency gate.
- Logs to `preamble.log` at WARNING for non-security misses, ERROR for security events
  (tarball bombs).
- Does NOT sleep internally — caller provides the sleep via `politeness_sleep()`.

The `notebook_fetch.run()` loop must call `politeness_sleep(request_start)` AFTER
the raw-tex fetch (separate from the ar5iv sleep), making the per-paper cost ~6s total.

For the `make ingest-recover-preambles` back-fill target: implement as a standalone
Python script (e.g. `tools/recover_preambles.py`) invoked by the Makefile, NOT a shell
loop. This allows proper error capture, `preamble.log` writing, and test coverage.

Tool-schema is untouched (X-1 confirmed). BP1 SHA is untouched (X-2 confirmed — no
changes to `server/prompts.py` or `server/tools.py`). KMP_DUPLICATE_LIB_OK guard in
`tests/conftest.py` is not touched. No `CHUNKER_VERSION` bump.

---

## Open questions

1. **Back-fill target scope:** The scan brief says "65 ar5iv-only papers without
   preambles." The live `var/arxmcp/corpus/parsed/` has 137 subdirectories and
   `var/arxmcp/corpus/raw/` has 0. This means ALL 137 parsed papers are missing raw
   `.tex`. The "65" figure likely refers to the notebook papers specifically, not the
   full corpus. The back-fill target should walk all 137 by default but allow
   `ARGS="--notebook=<slug>"` scoping. The implementer should confirm this count via
   `ls var/arxmcp/corpus/parsed/ | wc -l` at implementation time.

2. **Should `fetch_raw_tex_if_missing` also call `extract_preamble`?** The roadmap
   brief says the helper "Returns `True` on success, `False` on skip" and the caller
   (notebook_fetch) does not abort on `False`. But the back-fill script needs to also
   call `extract_preamble` after fetching. The helper should fetch-only; `extract_preamble`
   should be called explicitly by both `notebook_fetch.py` (post-fetch) and the
   back-fill script. This matches the existing pattern in `fetch_seed.py` where
   `fetch_eprint` and `parse_with_latexml` are called separately.

3. **Withdrawn paper handling in `notebook_fetch.py` summary line:** The current
   summary format is `fetched=N from_cache=M missing=K rate_limited=R malformed=J`.
   When raw-tex fetch fails (404/withdrawn), should it add a new counter
   `raw_tex_missing=K2` or fold into the existing `missing` bucket? Recommendation:
   add a separate `raw_tex_skipped=K2` field in the summary so operators can distinguish
   ar5iv-missing papers from raw-tex-missing papers.

---

## External writes the implementation will require

None — this milestone is purely local.

The only external requests are `GET https://export.arxiv.org/e-print/<paper_id>` calls
during operator-initiated back-fill runs, which are not "external writes" in the
pipeline sense (no git push, no PR, no infra mutation, no API key required beyond
`ARXMCP_CONTACT_EMAIL` for the User-Agent header).
