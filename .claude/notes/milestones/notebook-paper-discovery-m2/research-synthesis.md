# Research Synthesis — notebook-paper-discovery-m2

**Orchestrator merge of research-brief-1 (in-codebase) + research-brief-2 (external/failure-modes)**
**Milestone:** Reusable arXiv Atom API library (epic e1, enabler). Implement INLINE.
**Verdict:** Pure-local refactor + generalization. No external writes. No MCP tool, no BP1 change.

---

## 1. Scope

Extract the arXiv Atom API surface from `tools/curate_seed.py` into a new shared
`tools/_arxiv_api.py` (mirroring `tools/_notebook_common.py`), generalize the query builder
to compose `cat:` + `abs:`/`ti:` clauses, add bounded pagination with injectable politeness
sleep, harden the XML parse, and rewire `curate_seed.py` as a thin re-exporting wrapper with
**no behavior change**. This is the reusable library m3's discovery driver consumes.

**OUT of scope (m3–m4):** the `discover_for_notebook` driver, dedup-against-corpus, the
operator-console Discover panel, S2/OpenAlex channels, any MCP tool.

---

## 2. What moves vs what stays (verified, brief-1 §In-codebase)

`tools/curate_seed.py` today (brief-1 quoted lines 15-41, 68-134):
```python
ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
def build_query_url(category: str, start: int, max_results: int) -> str: ...   # only cat:
def parse_atom_feed(xml_bytes: bytes) -> list[Candidate]: ...                  # stdlib xml.etree
def filter_candidates(...) -> list[Candidate]: ...                            # CLI heuristic
def fetch_candidates(category, max_results, contact_email=None) -> bytes: ...  # single page
```

**Move to `tools/_arxiv_api.py`:** `ARXIV_API_URL`, `ATOM_NS`, the `Candidate` dataclass,
`build_query_url` (generalized), `parse_atom_feed` (hardened), a private `_fetch_url(...)`
helper, and `fetch_candidates` (paginating + sleep-injected, returns `list[Candidate]`).
`__all__ = ["Candidate", "build_query_url", "fetch_candidates", "parse_atom_feed"]`.

**Stay in `tools/curate_seed.py`:** `filter_candidates` (year/category/abstract-length human-
curation heuristic) and `main()` (CLI). The module **re-exports** the moved names so existing
imports keep resolving (see §3).

**Honor (import, do NOT redefine):** `tools/arxiv_fetch.py:35` `POLITENESS_SLEEP_SECONDS = 3.0`
and `build_user_agent`. The new library imports the constant by name as its default sleep
interval (both briefs).

---

## 3. The re-export contract (load-bearing — AC "existing tests pass unchanged")

`tests/test_fetch_seed.py` imports directly (brief-1 lines 90-98):
```python
from tools.curate_seed import (Candidate, build_query_url, filter_candidates, parse_atom_feed)
```
and `TestCurateQueryURL` calls `build_query_url("math.AG", start=0, max_results=200)` and
`build_query_url("math.AG", 0, 10)` — **positional `start`, `max_results`**.

**Resolution (both briefs agree → re-export):** `curate_seed.py` does
`from tools._arxiv_api import Candidate, build_query_url, fetch_candidates, parse_atom_feed`
so the test imports resolve unchanged. **CRITICAL constraint on the generalized signature:**
the existing positional calls `build_query_url("math.AG", 0, 10)` must still work AND produce
a byte-identical URL to today (the test asserts URL content). So `build_query_url`'s first
three positional params must remain compatible. Recommended signature that satisfies this:

```python
def build_query_url(
    category: str,
    start: int = 0,
    max_results: int = 200,
    *,
    abs_keywords: str | None = None,
    ti_keywords: str | None = None,
) -> str:
```

(Note: brief-1 proposed keyword-only `start`/`max_results`; that would BREAK the positional
`build_query_url("math.AG", 0, 10)` test. **Orchestrator decision: keep `start`/`max_results`
positional** as today, add `abs_keywords`/`ti_keywords` as keyword-only. With both keywords
`None`, the produced URL must equal today's output exactly so `TestCurateQueryURL` passes.)

---

## 4. Implementation decisions (open questions resolved)

1. **`Candidate` location:** move to `_arxiv_api.py`, re-export from `curate_seed.py` (both
   briefs). Preserves `from tools.curate_seed import Candidate`.
2. **`fetch_candidates` return type → `list[Candidate]`** (brief-1 OQ1), owning pagination +
   parse internally. It is NOT imported by the existing tests, so changing its return is safe.
3. **No-behavior-change for curate_seed via bounded pagination (orchestrator refinement):**
   `fetch_candidates` pages in chunks of ≤2000 until it has collected `max_results` candidates
   OR the feed is exhausted. curate_seed's default `max_results=200` ≤ 2000 → **exactly one
   request** (start=0), identical to today. Pagination only engages when a caller (m3) asks
   for >2000. This satisfies AC "no behavior change" while delivering the pagination AC.
4. **Keyword quoting → QUOTED phrase (resolves brief-1 OQ2 + closes brief-2 FM-3):** compose
   `abs:"{abs_keywords}"` / `ti:"{ti_keywords}"`. Double-quoting gives exact-phrase relevance
   AND neutralizes query-syntax injection (an operator `description` like
   `stability AND cat:hep-th` becomes a literal phrase, not injected boolean logic). Strip any
   embedded `"` from the keyword before quoting (defensive; description already has control
   chars stripped per m1). URL-encode the whole `search_query` via `urllib.parse.urlencode`
   (the existing, working pattern — do not double-encode).
5. **XML parse → `defusedxml.ElementTree` (brief-2 FM-1, strong):** `defusedxml>=0.7` is
   already a dep (`pyproject.toml:139`), used by `server/retrieval/equations.py`. The arXiv
   Atom parse in curate_seed is the ONLY remaining stdlib `xml.etree` consumer of untrusted
   external data — migrating closes the XXE/billion-laughs gap (Threat 7,
   `08-security-observability-ops.md`) and removes an inconsistency. defusedxml is API-
   compatible for `fromstring`; the SAMPLE_FEED fixture (no DTD/entities) parses identically,
   so the existing parse test passes unchanged.

---

## 5. Failure modes → required mitigations (brief-2, all in-scope)

| FM | Trigger | Mitigation (REQUIRED) |
|---|---|---|
| FM-1 | Hostile/MITM Atom XML (XXE, billion-laughs) | `defusedxml.ElementTree.fromstring` (not stdlib). |
| FM-2 | Pagination runaway / missing totalResults | Three guards: stop on empty page; never `start >= 30000` (API cap); collected ≥ `max_results` stops. Bound pages by `ceil(max_results/page)`. |
| FM-3 | Query-syntax injection via operator keywords | Quote keyword phrases (`abs:"…"`), strip embedded `"`, URL-encode the search_query. |
| FM-4 | No sleep between pages → 503/IP block | Call the injected `sleep(POLITENESS_SLEEP_SECONDS)` BETWEEN pages (only when paginating; single-page path need not sleep, matching curate_seed today). |
| FM-5 | 0 results / >30000 results | 0 → empty list (callers handle). >30000 → log WARNING, stop at the cap. Add a modest content-length read cap on the raw response. |
| FM-6 | arXiv "error entry" (HTTP 200 + error `<summary>`, `<id>` contains `/api/errors#`) | `parse_atom_feed` detects the `/api/errors#` id and raises `RuntimeError` with the summary. |

---

## 6. Test plan (brief-1 §graph_ingest pattern)

New `tests/test_arxiv_api.py`, HTTP layer mocked via `monkeypatch.setattr(_arxiv_api, "_fetch_url", stub)` (the `graph_ingest._fetch_openalex_work` monkeypatch pattern,
`tests/test_graph_ingest.py:101-122`) — never patch `urllib.request.urlopen` globally:
- `build_query_url`: no-keywords output == legacy URL (byte-stable, guards §3); `abs_keywords`
  composes `cat:… AND abs:"…"`; `ti_keywords`; both; positional `("math.AG", 0, 10)` works.
- `build_query_url` injection: a keyword `'x AND cat:hep-th'` ends up inside the quoted phrase
  (no bare `AND cat:` in the decoded search_query).
- `parse_atom_feed`: round-trips a sample feed (reuse `test_fetch_seed.py`'s SAMPLE_FEED);
  detects an `/api/errors#` entry and raises (FM-6).
- `fetch_candidates`: single page for `max_results=200` (one `_fetch_url` call, `sleep` NOT
  called between pages); multi-page for `max_results>2000` (sleep called between pages, FM-4);
  empty-page termination (FM-2).
- `curate_seed` re-export smoke: `from tools.curate_seed import Candidate, build_query_url,
  fetch_candidates, parse_atom_feed` resolves.
- Confirm `tests/test_fetch_seed.py` passes unchanged.

---

## 7. Orchestrator synthesis note (divergences resolved)

- **`build_query_url` signature:** brief-1 made `start`/`max_results` keyword-only; that would
  break `TestCurateQueryURL`'s positional `build_query_url("math.AG", 0, 10)`. **Resolved →
  keep them positional**, add `abs_keywords`/`ti_keywords` keyword-only, and require the
  no-keywords URL to be byte-identical to today.
- **defusedxml:** brief-2 raised it; brief-1 left stdlib. **Resolved → migrate to defusedxml**
  (already a dep; security + consistency; API-compatible).
- **Keyword quoting:** brief-1 leaned unquoted, brief-2 leaned quoted-for-injection-safety.
  **Resolved → quoted phrase** (closes FM-3 + better relevance; strip embedded `"`).
- **`fetch_candidates` pagination vs no-behavior-change:** **Resolved → bound by `max_results`**
  so curate_seed's 200 stays one request (identical) while >2000 paginates.
- Both confirm: no MCP tool, `EXPECTED_TOOL_SCHEMA_SHA256` unchanged, no-fork (reimplement
  natively; do NOT import arxiv.py), no `assert` (use `if … raise`), no new pip dep.

## 8. Open questions

None blocking. The two from the briefs (`Candidate` re-export; `fetch_candidates` return type)
are resolved in §3–§4.

## 9. External writes required

**None.** New file `tools/_arxiv_api.py`, modified `tools/curate_seed.py` (re-export wrapper),
new `tests/test_arxiv_api.py`. No push, PR, ticket, infra, or third-party write. Both briefs
independently confirm. `state.external_writes_required = []`.
