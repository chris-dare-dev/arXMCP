# Research Brief — notebook-paper-discovery-m2

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-31T17:05:00Z

---

## In-codebase context

### What curate_seed.py currently exposes (verbatim signatures)

`tools/curate_seed.py` lines 68-134:

```python
ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

def build_query_url(category: str, start: int, max_results: int) -> str:
    params = {
        "search_query": f"cat:{category}",
        "start": str(start),
        "max_results": str(max_results),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}"

def parse_atom_feed(xml_bytes: bytes) -> list[Candidate]:
    # returns list[Candidate]; uses ATOM_NS; strips version suffix from paper_id
    ...

def filter_candidates(candidates, primary_category, min_year, min_abstract_chars) -> list[Candidate]:
    # pure filter; stays in curate_seed.py (CLI-specific heuristic)
    ...

def fetch_candidates(category: str, max_results: int, contact_email: str | None = None) -> bytes:
    url = build_query_url(category, start=0, max_results=max_results)
    req = urllib.request.Request(url, headers={"User-Agent": build_user_agent(contact_email)})
    with urllib.request.urlopen(req, timeout=60.0) as resp:
        return resp.read()
```

**Classification — pure (movable) vs CLI-coupled:**

- `build_query_url` — pure + movable; but current signature lacks `abs_keywords`/`ti_keywords` — the milestone generalizes it.
- `parse_atom_feed` — pure + movable; `Candidate` dataclass must also move to `_arxiv_api.py` because m3's driver needs it.
- `fetch_candidates` — movable; needs `sleep` injection and pagination added.
- `filter_candidates` — CLI-specific heuristic (year/category/abstract-length filter for human review); stays in `curate_seed.py`.
- `ARXIV_API_URL`, `ATOM_NS` constants — move with the functions.
- `main()` — stays in `curate_seed.py` (CLI entry point).

**Constants from `tools/arxiv_fetch.py` that must be honored** (lines 35-36):
```python
POLITENESS_SLEEP_SECONDS = 3.0
DEFAULT_503_BACKOFF_SECONDS = 30.0
```
`_arxiv_api.py` imports `POLITENESS_SLEEP_SECONDS` from `tools.arxiv_fetch` as its default floor for inter-page sleeps — do NOT redefine the constant; import it.

### tools/_notebook_common.py precedent

The shared-module pattern: a `tools/_<name>.py` file with `from __future__ import annotations`, `__all__` export list, typed helpers, and an explicit `NotebookError` subclass for domain errors. The module exposes only what callers need; no `main()`. The new `tools/_arxiv_api.py` mirrors this exactly.

Key style constraints from `_notebook_common.py`:
- All path constants resolved from `__file__` (not CWD).
- No runtime `anthropic` import (CLAUDE.md §4.7).
- `if … raise RuntimeError/NotebookError` — never `assert`.

### The m1 contract this library serves

From `.claude/notes/notebook-discovery-model.md` §1 (verbatim):
> `discovery_category` … enum `{math.AG, math.NT, math-ph, hep-th}` **or empty**; enforced at the route layer by `server/routes/notebooks.py::_validate_discovery_category`
> `description` … free text … `the abs:/ti: keyword clause in the m2/m3 query`

The library's `build_query_url` receives the description field value as `abs_keywords`. The four valid category strings are: `math.AG`, `math.NT`, `math-ph`, `hep-th`.

### No-fork and no-anthropic-SDK constraints

From `CLAUDE.md §4.7` (verbatim):
> **`assert` is BANNED for invariants** — Python `-O` strips them. Use `if … raise RuntimeError(…)` instead.
> **No `anthropic` SDK at runtime.** The server is a tool provider; the LLM lives in the calling agent.

From `CLAUDE.md §4.7` (no-fork): **"No-fork policy. Nothing lifted from existing `arxiv-mcp` repos."**

---

## Prior decisions and lessons

### Existing tests (file:line)

`tests/test_fetch_seed.py` imports from `tools.curate_seed` directly:
```python
from tools.curate_seed import (
    Candidate,
    build_query_url,
    filter_candidates,
    parse_atom_feed,
)
```

Test class `TestCurateQueryURL` (lines 72-83) calls:
- `build_query_url("math.AG", start=0, max_results=200)` — positional `start` + `max_results`
- `build_query_url("math.AG", 0, 10)` — fully positional

**CRITICAL — these tests MUST continue to pass unchanged.** After extraction, `curate_seed.py` must re-export `build_query_url`, `parse_atom_feed`, and `Candidate` from `_arxiv_api.py` so the import line `from tools.curate_seed import Candidate, build_query_url, ...` in `tests/test_fetch_seed.py` still resolves without modification.

### The graph_ingest monkeypatch pattern (tests/test_graph_ingest.py:101-122)

```python
monkeypatch.setattr(graph_ingest, "_fetch_openalex_work", _stub)
```

The stub replaces the private `_fetch_openalex_work` function directly on the module object. New tests for `_arxiv_api.py` should do the same: define a `_fetch_url` (or similar private) function inside `_arxiv_api.py` that makes the actual `urllib.request.urlopen` call, and monkeypatch `_arxiv_api._fetch_url` in tests. This avoids patching `urllib.request.urlopen` globally (which is fragile) and matches the established pattern.

### Recent git log

- `babe092` — `chore(notes): finalize notebook-paper-discovery-m1 state -> complete`
- `31ec0e9` — `rect(server): close F1 MEDIUM from notebook-paper-discovery-m1 critique`
- `82e3ba5` — `feat(server,tools): notebook topic metadata + discovery-model note (notebook-paper-discovery-m1)`

m1 is complete. m2 state.json shows `phase: research-running` (this run). No prior m2 artifacts.

### m1 deferred finding F2 (from state.json)

F2 was deferred from m1 critique. The m1 critique file is at `.claude/notes/milestones/notebook-paper-discovery-m1/critique-adversary.md`. The finding was deferred — check if it touches `curate_seed.py` before implementing. (The deferred findings list is short; F1 was fixed, F2 deferred but unrelated to the m2 scope based on m1's narrow migration focus.)

### Tool-schema stability

m2 adds NO MCP tools. Per `.claude/notes/notebook-discovery-model.md` §2 (verbatim):
> **No new MCP tool in v1.** … `EXPECTED_TOOL_SCHEMA_SHA256` and the BP1 prefix stay byte-stable.

**`EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning for m2.**

---

## External sources

### arXiv API search_query syntax (info.arxiv.org/help/api/user-manual.html, 2026-05-31)

- Field prefixes: `cat:` (category), `abs:` (abstract), `ti:` (title), `au:` (author), `all:`.
- Boolean composition: `AND`, `OR`, `ANDNOT`. Example: `cat:math.AG AND abs:Bridgeland stability`.
- Multi-word phrases need URL-encoded quotation marks: `abs:%22Bridgeland+stability%22` for exact phrase. Spaces become `+` in the query string.
- `max_results` cap: **2,000 per request**; **30,000 total** across paginated calls.
- `start` parameter: zero-based offset. Pagination: call with `start=0`, `start=2000`, `start=4000`, etc., each time sleeping ≥3s between calls.

**Encoding recommendation:** use `urllib.parse.urlencode({"search_query": query_string})` where `query_string` is built as a Python string (e.g. `"cat:math.AG AND abs:Bridgeland stability"`). `urlencode` with default `quote_via=quote_plus` will encode spaces as `+` and reserved chars as `%XX` — this is the correct form for the arXiv API query parameter. Do NOT double-encode the `cat:` prefix.

---

## Recommendation

**Extract exactly these three entities into `tools/_arxiv_api.py`:** `ARXIV_API_URL`, `ATOM_NS`, `Candidate` (dataclass), `build_query_url` (generalized), `parse_atom_feed`, and a private `_fetch_url(url, contact_email)` helper used by `fetch_candidates`. Keep `filter_candidates` and `main()` in `curate_seed.py`.

**Recommended new signature for `build_query_url`:**
```python
def build_query_url(
    category: str,
    *,
    abs_keywords: str | None = None,
    ti_keywords: str | None = None,
    start: int = 0,
    max_results: int = 200,
) -> str:
```
Compose `search_query` as: `cat:{category}` base, then `AND abs:{abs_keywords}` if provided, then `AND ti:{ti_keywords}` if provided. Pass the composed string as one value to `urllib.parse.urlencode` — `urlencode` will quote spaces as `+` correctly.

**Recommended `fetch_candidates` signature (with sleep injection):**
```python
def fetch_candidates(
    category: str,
    max_results: int,
    contact_email: str | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Candidate]:
```
This fetches ALL pages (loop over `start=0, 2000, 4000, ...` until the feed is empty or `max_results` reached), sleeping `POLITENESS_SLEEP_SECONDS` between pages using the injected `sleep`. The injected `sleep` is for tests to pass a no-op; production code calls with default `sleep=time.sleep`.

**Rewiring `curate_seed.py`:** thin wrapper that does:
```python
from tools._arxiv_api import (
    ARXIV_API_URL, ATOM_NS, Candidate,
    build_query_url, fetch_candidates, parse_atom_feed,
)
```
The existing positional call `build_query_url(category, start=0, max_results=200)` in `curate_seed.py`'s `fetch_candidates` wrapper becomes a direct delegation. The re-export ensures `tests/test_fetch_seed.py` imports (`from tools.curate_seed import Candidate, build_query_url, ...`) keep working.

**`__all__` in `_arxiv_api.py`:** `["Candidate", "build_query_url", "fetch_candidates", "parse_atom_feed"]`.

**New test file:** `tests/test_arxiv_api.py`. Use `monkeypatch.setattr(_arxiv_api, "_fetch_url", stub)` — the graph_ingest pattern. Test: `build_query_url` with abs_keywords + ti_keywords produces correct `search_query`; pagination loop calls `sleep` between pages; `parse_atom_feed` round-trips the SAMPLE_FEED fixture from `test_fetch_seed.py` (no duplication — just reuse the XML string constant or move it to a shared fixture).

---

## Open questions

1. **`fetch_candidates` return type:** the current `curate_seed.py` `fetch_candidates` returns `bytes` (raw XML), and the caller invokes `parse_atom_feed(feed_bytes)` separately. The m3 discovery driver will want `list[Candidate]` directly. The recommended signature above returns `list[Candidate]` (it calls `parse_atom_feed` internally). This changes the interface curate_seed.py uses. Implementer must decide: keep `fetch_candidates` returning `bytes` and add a higher-level `fetch_and_parse_candidates(...)` returning `list[Candidate]`, OR change `fetch_candidates` to return `list[Candidate]` and update `curate_seed.py`'s usage. **Recommendation: change `fetch_candidates` to return `list[Candidate]`** — the bytes-returning version is not needed by any other caller, and having `fetch_candidates` own pagination+parse makes it the single entry point the m3 driver needs. Update `curate_seed.py` to drop its explicit `parse_atom_feed(feed_bytes)` call.

2. **Multi-word `abs:` keyword quoting:** the arXiv API supports both `abs:Bridgeland stability` (unquoted — matches each word independently) and `abs:%22Bridgeland+stability%22` (quoted — exact phrase match). The m1 `description` field stores the full free-text phrase. The implementer should use the **unquoted form** (words joined by spaces, `urlencode` handles encoding) unless the caller explicitly wants exact-phrase semantics. The quote-wrapped form can be left as a future enhancement (relevant `search_query` would be `cat:math.AG AND abs:"Bridgeland stability"`).

No other open questions — implementation can proceed on the above recommendation.

---

## External writes the implementation will require

None — this milestone is purely local.

All changes are: new file `tools/_arxiv_api.py`, modified `tools/curate_seed.py` (thin wrapper), new test file `tests/test_arxiv_api.py`, `make test` green. No git push, no GitHub issues, no infra mutations.
