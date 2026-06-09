# Research Brief — oldstyle-id-ingest-fix-m1

**Agent:** milestone-researcher (brief-1, single-mode)
**Generated:** 2026-06-04T02:30:00Z

## In-codebase context

### Fix 1 — `ingest/ar5iv_fetch.py` `try_cache()` cache-dir creation

`try_cache()` derives the cache path at line 152:

```python
cache_path = cache_dir / f"{paper_id}.html"
```

For old-style IDs (e.g. `math/0212237`) this resolves to
`cache_dir/math/0212237.html` on all platforms including Windows
(Python `pathlib` treats a forward-slash in the string argument as a
path separator on all platforms — verified live on Windows 11). The
`math/` subdir is `cache_path.parent`, distinct from `cache_dir`.

The pre-fix code wrote:

```python
cache_dir.mkdir(parents=True, exist_ok=True)
```

This only creates `cache_dir` itself (`var/arxmcp/cache/ar5iv/`), not
the `math/` subdir one level deeper. The `cache_path.write_text(...)` on
the next line then raises `FileNotFoundError` on a fresh tree.

The fix replaces it with:

```python
cache_path.parent.mkdir(parents=True, exist_ok=True)
```

This is correct for both old-style IDs (`math/` subdir is created) and
new-style IDs (`cache_path.parent == cache_dir`, so no difference).

The `parsed_paper_dir.mkdir(parents=True, exist_ok=True)` line below it
was already correct: `parsed_paper_dir = parsed_dir / paper_id` creates
the full nested path, including the `math/` subdir for old-style IDs.

**Validation is in `is_valid_arxiv_paper_id` (from `ingest/identifiers.py`),
called at the top of `try_cache()` before any path construction. That
function accepts old-style IDs** per the pattern:

```python
_ARXIV_PAPER_ID_FULL_PATTERN = (
    r"^\d{4}\.\d{4,5}(v\d+)?\Z"          # new style
    r"|"
    r"^[a-z][a-z\-]*/\d{7}(v\d+)?\Z"    # old style: hep-th/0001234
)
```

So old-style IDs pass validation and reach the path construction code.

**Windows portability:** Confirmed live that `Path('/tmp/cache') / 'math/0212237.html'`
resolves to `\tmp\cache\math\0212237.html` and
`cache_path.parent.mkdir(parents=True, exist_ok=True)` successfully
creates the `math\` subdir. Old-style IDs use `/` (forward slash), not `:`
(colon), so this does NOT add to the 29 pre-existing Windows colons-in-filenames
failures. This is safe on Windows.

### Fix 2 — `tools/notebook_fetch.py` `run()` ValueError guard

The call chain is:
1. `run()` calls `fetch_raw_tex_if_missing(paper_id, CORPUS_RAW_DIR)` (from `tools/_notebook_common.py`)
2. `fetch_raw_tex_if_missing` calls `fetch_eprint(paper_id, raw_dir, ...)` (from `tools/arxiv_fetch.py`)
3. `fetch_eprint` calls `validate_paper_id(paper_id)` at line 273

`validate_paper_id` in `tools/arxiv_fetch.py` (line 127–139) is:

```python
def validate_paper_id(paper_id: str) -> None:
    """Reject anything that is not a new-style YYMM.NNNNN[N] arXiv ID.

    The seed corpus is post-2010 math.AG — old-style `subject/NNNNNNN`
    IDs do not appear there and pre-2007 OCR-only papers are an explicit
    non-goal per .claude/notes/09-feature-priorities.md.
    """
    if not PAPER_ID_RE.match(paper_id):
        raise ValueError(
            f"paper_id {paper_id!r} does not match new-style arXiv ID ..."
        )
```

`PAPER_ID_RE` in `tools/arxiv_fetch.py` is `re.compile(r"^[0-9]{4}\.[0-9]{4,5}$")` — **new-style only**. Old-style IDs like `math/0212237` will never match this pattern and unconditionally raise `ValueError`.

The pre-fix code had:

```python
if fetch_raw_tex_if_missing(paper_id, CORPUS_RAW_DIR):
    raw_tex_recovered.append(paper_id)
else:
    raw_tex_missing.append(paper_id)
```

This did not catch `ValueError` propagating from `validate_paper_id` through
`fetch_eprint` through `fetch_raw_tex_if_missing`. **`fetch_raw_tex_if_missing`'s
own docstring does NOT list `ValueError` in its exception envelope** — it lists
only `urllib.error.HTTPError`, `RuntimeError`, `OSError`, `tarfile.TarError`, and
`gzip.BadGzipFile`. So the `ValueError` escaped the helper and aborted the batch.

The fix wraps only the call and captures the exception as `raw_tex_missing`:

```python
try:
    recovered = fetch_raw_tex_if_missing(paper_id, CORPUS_RAW_DIR)
except ValueError:
    # Old-style ids ... degrade to raw_tex_missing rather than aborting
    recovered = False
```

**IMPORTANT: The bare `except ValueError` scope is narrow** — it wraps only
`fetch_raw_tex_if_missing(paper_id, CORPUS_RAW_DIR)`. The only `ValueError`
this call can raise under normal operation is from `validate_paper_id` inside
`fetch_eprint`. However, `fetch_raw_tex_if_missing` itself has an idempotency
check before calling `fetch_eprint`: if the raw dir already has `.tex` files, it
returns `True` without calling `fetch_eprint` at all. A `ValueError` could in
theory arise from an unexpected source, but the call surface is narrow and
one level deep; see the Open Questions section for the risk assessment.

**The module-level docstring states:**
> `raw_tex_missing` covers all non-OK raw-tex outcomes (404 withdrawn, 503
> rate-limited, tarball errors); see `preamble.log` for per-paper reasons.

Degrading to `raw_tex_missing` on old-style ID is semantically correct per
this contract.

### Existing test conventions

`tests/test_ar5iv_fetch.py` is the sole test file for `ingest/ar5iv_fetch.py`.
It uses `unittest.mock.patch` to mock `ingest.ar5iv_fetch.urllib.request.urlopen`,
passes `tmp_path` as `cache_dir` and `parsed_dir`, and uses a local `_FakeResponse`
stub class. All tests live in a single `TestTryCache` class, using plain methods
(not `@pytest.mark.parametrize`). No async. No network. No conftest autouse except
the global ones (store-stats, BM25, cache-db).

**There is no `tests/test_notebook_fetch.py`.** New tests for `notebook_fetch.py`
must be added in a new file following the same conventions as `test_ar5iv_fetch.py`:
`unittest.mock.patch` for network calls, `tmp_path` for filesystem isolation,
inline stub classes for fakes, class-based grouping.

The `_notebook_common` module attributes (e.g., `CORPUS_RAW_DIR`, `NOTEBOOKS_BASE`)
are patched via `monkeypatch.setattr` in existing notebook tests (see
`tests/test_notebook_api.py`). The `notebook_fetch.run()` function uses module-level
constants `DEFAULT_AR5IV_CACHE_DIR`, `DEFAULT_PARSED_DIR`, `CORPUS_RAW_DIR` — for
testing, pass overridden `cache_dir`/`parsed_dir` to `try_cache` (via
`tools/notebook_fetch.py` calling `try_cache` with those defaults), or mock
`ingest.ar5iv_fetch.try_cache` directly to return a controlled `Ar5ivResult`.

The cleanest approach for `notebook_fetch` tests: mock both
`ingest.ar5iv_fetch.try_cache` (to return a controlled `Ar5ivResult` without
needing a real tmp filesystem tree) and
`tools._notebook_common.fetch_raw_tex_if_missing` (to control the raw-tex outcome).
Also mock `tools.notebook_fetch.time.sleep` to skip the politeness sleep.
Use `monkeypatch.setattr(tools._notebook_common, "NOTEBOOKS_BASE", tmp_path / "notebooks")`
plus write a real `papers.txt` file in the notebook dir.

## Prior decisions and lessons

**Recent git log (last 20):** The recent commits are all on `main`. The last
milestone commit was `feat(server): fix htmx JSON encoding (ui-htmx-json-fix-m1)`.
There are no in-flight milestones conflicting with this work area.

**Prior critique history for old-style IDs:** E09_S02 F2 ("validate_paper_id
rejects old-style arXiv IDs, blocking hep-th enrichment") was an identical
pattern found in INSPIRE ingest. The fix there was to use `is_valid_arxiv_paper_id`
from `ingest/identifiers.py`. The `tools/arxiv_fetch.py::validate_paper_id` was
intentionally left as new-style-only with documented rationale
("old-style IDs do not appear in the seed corpus"). This milestone does NOT change
that function; it catches the exception at the call site instead.

**CLAUDE.md §8 landmine #1:** `KMP_DUPLICATE_LIB_OK=TRUE` is set in
`tests/conftest.py` at import time. Do not remove it. New test files do not need
to set it themselves — it fires autouse.

**No tool-schema change:** this milestone touches no MCP tool definitions.
`EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py` does NOT need
re-pinning.

**No new Markdown files outside `.claude/`:** regression tests go in
`tests/test_ar5iv_fetch.py` (extend the existing file) and a new
`tests/test_notebook_fetch.py`. No doc files needed.

**Commit convention:** single `feat(ingest,tools)` commit covering both fixes and
tests, plus a `rect(...)` if critique finds anything, plus `chore(notes)` to
finalize state. GPG-signed, HEREDOC form, co-author trailer required.

## External sources

This is a local bugfix with no MCP surface change. No external API or spec
consultation is required.

**arXiv old-style identifier scheme (from existing codebase comments):** Old-style
arXiv IDs use the format `<archive>/YYMMNNNN` (e.g. `math/0212237`, `hep-th/9711200`).
The archive component matches `[a-z][a-z\-]*` (letters and hyphens, no dots — per
the `_ARXIV_PAPER_ID_FULL_PATTERN` in `ingest/identifiers.py`). Digit count is
exactly 7 (`\d{7}`). Optional version suffix `vN`. The slash is a literal separator
and is part of the arXiv canonical form, not a filesystem path separator.

**No MCP-spec surface change.** No Anthropic prompt-caching docs relevant.

**Risk analysis of the fixes themselves:**

1. **`cache_path.parent.mkdir` masking a deeper path-construction bug?**
   No. The root cause is clear: old-style IDs contain a literal `/` which `pathlib`
   resolves as a subdir. `cache_path.parent.mkdir(parents=True)` is the minimal
   correct fix. No deeper path-construction issue exists.

2. **Does `except ValueError` swallow ValueErrors from causes OTHER than
   old-style-id rejection?** Low risk. The only code path inside
   `fetch_raw_tex_if_missing` that can raise `ValueError` is:
   (a) `fetch_eprint` → `validate_paper_id` (old-style ID, the intended case),
   (b) conceivably an unexpected internal Python conversion error, but
   `fetch_raw_tex_if_missing` is a pure-Python function with a narrow call graph
   (rglob + late import + `fetch_eprint`). The risk is low enough that bare
   `except ValueError` at this call site is acceptable. Adding a comment in the
   except clause (as the existing code already has) is sufficient documentation.
   The downside of a masked unexpected ValueError is that it shows as `raw_tex_missing`
   in the summary and in `preamble.log`, which operators will see and can investigate.
   This is not silent data corruption.

3. **Is `raw_tex_missing` the right bucket vs a new `raw_tex_skipped`?**
   The module docstring is explicit: "`raw_tex_missing` covers all non-OK raw-tex
   outcomes (404 withdrawn, 503 rate-limited, tarball errors)". Old-style ID
   out-of-scope for `fetch_eprint` is a non-OK outcome. Using `raw_tex_missing`
   is semantically correct and consistent with the documented contract. No new
   bucket is needed.

## Recommendation

Add regression tests in two locations:

1. **Extend `tests/test_ar5iv_fetch.py`** with a new test class
   `TestOldStyleId` (or add two tests to `TestTryCache`). Tests to add:
   - `test_old_style_id_creates_subject_subdir`: call `try_cache("math/0212237", ...)`
     with a `_FakeResponse` returning a valid `<math>` body; assert that
     `cache_dir / "math" / "0212237.html"` exists and `parsed_dir / "math" / "0212237" / "index.html"`
     exists. This is the direct regression for fix (1).
   - `test_old_style_id_local_cache_hit`: pre-populate both paths under the
     subject subdir; assert `urlopen` is not called and `result.reason == "ok_local_cache"`.

2. **Create `tests/test_notebook_fetch.py`** with a `TestNotebookFetchRun` class.
   Test to add:
   - `test_old_style_id_does_not_abort_run`: build a minimal notebook dir in
     `tmp_path`, write a `papers.txt` with two IDs (`2401.00001` and
     `math/0212237`). Mock `ingest.ar5iv_fetch.try_cache` to return hit for both.
     Mock `tools._notebook_common.fetch_raw_tex_if_missing` to return `True` for
     `2401.00001` and raise `ValueError` for `math/0212237`. Mock
     `tools.notebook_fetch.time.sleep` to no-op. Assert: `run(slug, ...)` returns
     `0` (no malformed, no missing), summary contains
     `raw_tex_recovered=1 raw_tex_missing=1`. This is the direct regression for fix (2).
   - Also mock `tools.notebook_fetch.resolve_contact_email` to no-op (avoids
     SQLite/env lookup in test).

**Why this approach:** it mirrors exactly the convention in `test_ar5iv_fetch.py`
(offline mocking, `tmp_path`, class-based grouping). The notebook_fetch test
mocks at the module boundary rather than re-testing the network — consistent with
how existing notebook tests isolate against slow I/O. The `resolve_contact_email`
mock is the only deviation from a pure "just call the function" approach, and is
necessary because `run()` calls it at entry.

## Open questions

**One question requires a judgment call before writing the test:**

Should the regression test for fix (2) mock `tools._notebook_common.fetch_raw_tex_if_missing`
directly, OR should it mock the deeper `tools.arxiv_fetch.fetch_eprint`?

Recommendation: mock `tools._notebook_common.fetch_raw_tex_if_missing` directly.
Rationale: the test is verifying that `notebook_fetch.run()` handles a
`ValueError` from `fetch_raw_tex_if_missing` without aborting — the source of the
`ValueError` is irrelevant to this contract. Mocking the helper directly keeps the
test simple and avoids duplicating the existing `test_ar5iv_fetch.py` tests that
already cover `try_cache` behavior. The `fetch_eprint`/`validate_paper_id` chain
is already covered by E09_S02 tests.

This is a recommendation, not an open question requiring human resolution.

**No open questions — implementation can proceed on the above recommendation.**

## External writes the implementation will require

None — this milestone is purely local.
