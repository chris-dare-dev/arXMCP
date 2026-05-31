# Research Synthesis — notebook-paper-discovery-m3

**Orchestrator merge of research-brief-1 (in-codebase) + research-brief-2 (failure-modes)**
**Milestone:** arXiv Atom discovery driver for a notebook (epic e2, value). Implement INLINE.
**Verdict:** Purely-local. No external writes. No MCP tool, no BP1 change, LLM-free.

---

## 1. Scope

Add `tools/discover_for_notebook.py`: given a notebook slug, read its `discovery_category`
(m1) + `description` (m1, used as `abs_keywords`), query the m2 `_arxiv_api` library,
deduplicate candidates against the notebook's `notebook_papers` junction, and return a ranked
candidate list `(paper_id, title, abstract_head, submitted_date)`. Deterministic, LLM-free; the
driver PROPOSES, it does not auto-ingest (`notebook-discovery-model.md §2`).

**OUT of scope:** the operator-console Discover panel + HTTP route (m4), any MCP tool, the
S2/OpenAlex channels (e3).

---

## 2. The Candidate-shape gap (both briefs flag this — load-bearing)

The AC output is `(paper_id, title, abstract_head, submitted_date)`, but the shipped
`_arxiv_api.Candidate` (brief-1 lines 12-21) is:
```python
@dataclass(frozen=True)
class Candidate:
    paper_id: str
    submitted_year: int       # year only (int), NOT a date
    n_authors: int
    primary_category: str
    abstract_head: str
```
**No `title`; only `submitted_year`.** The Atom `<title>` is a required element (RFC 4287, brief-2
line 84) present in every entry, and the raw `<published>` ISO-8601 string is already read by
`parse_atom_feed` for the year then discarded (brief-1 lines 67-68).

**Resolution (both briefs recommend extending Candidate; orchestrator confirms):**
- Extend `_arxiv_api.Candidate` with **`title: str = ""`** and **`submitted_date: str = ""`**
  (raw ISO-8601 from `<published>`), appended AFTER the existing fields **with defaults** so the
  frozen dataclass stays backward-compatible with the existing keyword constructions in tests
  (`test_fetch_seed.py::TestFilterCandidates._candidate`, `test_arxiv_api.py::TestReExport`) and
  with `as_tsv_row` (unchanged 5-column output). All production construction is inside
  `parse_atom_feed` (keyword args), so there are no positional-construction sites to break.
- `parse_atom_feed` reads `entry.findtext("atom:title", …)` and keeps the raw published string
  (`submitted_year` retained for `as_tsv_row` + curate_seed back-compat).
- Keep XML parsing in ONE place (`_arxiv_api`), not duplicated in the driver.

This is an additive change to a shipped module, justified by m3's AC; it's the natural extension
(brief-1 §Recommendation, brief-2 line 122).

---

## 3. Driver design

### Output type (divergence resolved)
brief-1 → return `list[Candidate]` directly; brief-2 → a driver-owned `DiscoveryResult`.
**Resolved → a small driver-owned `DiscoveryCandidate` dataclass** exposing exactly the AC fields
`(paper_id, title, abstract_head, submitted_date)`, mapped from the extended `Candidate`. Rationale:
it is the AC's exact shape and a stable contract for m4's panel, decoupled from arXiv-internal
fields (`n_authors`, `primary_category`, `submitted_year`) that aren't part of the discovery
contract. XML parsing still lives once in `_arxiv_api` (we map, not re-parse).

### Structure (async core + sync/CLI wrapper — resolves the store-DI question)
The driver must `await` the store (`get_notebook`, `list_papers`) AND call the sync
`fetch_candidates`. So:
```python
@dataclass(frozen=True)
class DiscoveryCandidate:
    paper_id: str
    title: str
    abstract_head: str
    submitted_date: str

async def discover_for_notebook_async(
    store: NotebooksStore, slug: str, *,
    max_results: int = 200, contact_email: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[DiscoveryCandidate]: ...

def discover_for_notebook(
    slug: str, *, db_path: Path | None = None, max_results: int = 200,
    contact_email: str | None = None, sleep: Callable[[float], None] = time.sleep,
) -> list[DiscoveryCandidate]:
    # opens NotebooksStore(db_path or DEFAULT_DB_PATH), asyncio.run(core), closes store
```
- The **async core takes an open `store`** (brief-2's DI point) → tests call it directly with a
  tmp-db store + monkeypatched `_arxiv_api._fetch_url`.
- The **sync wrapper** opens the store and `asyncio.run`s the core (brief-1's `notebook_init.py`
  pattern, lines 107-119) — CLI-friendly, no event-loop ceremony for callers.
- db_path default: `from server.operator_settings import DEFAULT_DB_PATH` (= `var/arxmcp/cache/notebooks.db`,
  brief-1 line 131). The async core path matters; the sync wrapper opens via `NotebooksStore.open`
  (NOT the offline raw-sqlite reader — we need `list_papers`).

### Core logic
1. `nb = await store.get_notebook(slug)`; if `None` → `raise ValueError(f"notebook {slug!r} not found")`.
2. `category = nb["discovery_category"]`; if empty → `raise ValueError(f"notebook {slug!r} has no discovery_category set — set a topic first")` (brief-1: "not configured" ≠ "found nothing"; build_query_url would otherwise raise on empty category).
3. `keywords = nb["description"]` → passed as `abs_keywords` **unmodified** (m2 already strips control chars + quotes; do NOT re-process — brief-2 FM-e).
4. `cands = fetch_candidates(category, max_results, contact_email, abs_keywords=keywords or None, sleep=sleep)`.
5. `existing = {p["paper_id"] for p in await store.list_papers(slug)}` (un-versioned IDs; format aligned — brief-2 §dedup, line 55/108).
6. `return [DiscoveryCandidate(c.paper_id, c.title, c.abstract_head, c.submitted_date) for c in cands if c.paper_id not in existing]` — **order-preserving** filter (arXiv returns `sortBy=submittedDate desc`; deterministic for a fixed mock — brief-2 FM-c).

### CLI `main()`
Positional `slug` + `--max-results`/`--email`/`--db-path`/`--json`. `validate_slug(slug)` first
(brief-1 line 224). Prints TSV (or JSON) of candidates; clean error to stderr + exit 1 on
ValueError; exit 0 otherwise.

---

## 4. Failure modes → required mitigations (brief-2, all in-scope)

| FM | Trigger | Mitigation |
|---|---|---|
| a | slug missing / `discovery_category` empty | early-exit guards BEFORE any HTTP call → `ValueError` (not a degenerate query). |
| b | all candidates already in notebook | return `[]` (valid result, not an error); log INFO. |
| c | determinism / same-date ties | order-preserving list-comp filter over the arXiv-sorted list; fixed mock → fixed output. |
| d | versioned vs un-versioned IDs | both `parse_atom_feed` (`split("v",1)[0]`) and `add_paper` produce un-versioned IDs → dedup aligned (brief-2 line 55). |
| e | `description` → injection | pass through unmodified; m2's `_keyword_clause` already quotes+strips. No re-processing. |
| f | politeness on looped runs | per-page sleep inherited from m2; single-page (`max_results≤2000`) → no sleep. Inter-notebook sleep is a future caller's concern (m4); document in docstring. |

---

## 5. Security / constraints (security-reviewer specialist concern)

- **Egress unchanged:** the driver only reaches arXiv *through* `_arxiv_api` (only `export.arxiv.org`,
  TLS, `MAX_RESPONSE_BYTES` cap, polite User-Agent) — no new host, no non-loopback bind (brief-2 §egress).
- **Operator-data dedup is read-only** against `notebook_papers`; no write path.
- **No `assert`** (CLAUDE.md §4.7) — `if … raise` for all guards. **No `anthropic` SDK** (LLM-free).
- **No MCP tool** → `EXPECTED_TOOL_SCHEMA_SHA256` + BP1 unchanged. **No new pip dep** (`defusedxml`
  already present via m2). Markdown only under `.claude/` (no doc in `tools/`).

---

## 6. Test plan (HTTP mocked; the `_arxiv_api._fetch_url` + tmp-store pattern)

New `tests/test_discover_for_notebook.py` (async core called via `asyncio.run`, monkeypatch
`_arxiv_api._fetch_url`, `sleep=lambda _: None`, real `NotebooksStore` at `tmp_path/"notebooks.db"`):
- **Happy path (AC):** seed a notebook (`discovery_category="math.AG"`, `description="Bridgeland stability"`)
  + 1 junction paper that is also in the mocked feed; assert ≥1 returned AND the pre-existing
  paper_id is absent (dedup), and a returned candidate has non-empty `title` + `submitted_date`.
- **Determinism:** two calls with the same mocked feed → identical ordered output.
- **Empty `discovery_category` → ValueError**; **unknown slug → ValueError** (guards fire before HTTP).
- **All-deduped → `[]`** (every feed paper_id already in the junction).
- **Keywords flow:** the built query (capture via a `_fetch_url` stub recording the URL) contains
  `abs:"Bridgeland stability"`; a blank description → category-only query (no `abs:` clause).
- **Egress/politeness:** only one `_fetch_url` call for `max_results=200`; `sleep` not called.

Extend `tests/test_arxiv_api.py::TestParseAtomFeed` (or add) to assert `parse_atom_feed` now
populates `title` + `submitted_date` from the feed; confirm `tests/test_fetch_seed.py` +
existing `test_arxiv_api.py` pass unchanged (the new Candidate fields are defaulted).

---

## 7. Orchestrator synthesis note (divergences resolved)

- **Candidate extension:** both agree → extend `_arxiv_api.Candidate` with `title`/`submitted_date`
  (defaulted, additive). Single XML parse site.
- **Driver output type:** brief-1 `list[Candidate]` vs brief-2 `DiscoveryResult`. **Resolved → a
  driver-owned `DiscoveryCandidate`** with exactly the AC fields, mapped from the extended Candidate
  (clean m4 contract, decoupled from arXiv internals).
- **store DI:** brief-1 (open internally) vs brief-2 (inject store). **Resolved → both**: async core
  takes an injected `store` (testable); sync wrapper opens it (CLI). 
- **Empty category:** both → `raise ValueError` ("not configured" ≠ "found nothing").
- Both confirm: no MCP tool, no new dep, LLM-free, no-assert, egress unchanged.

## 8. Open questions

None blocking. The Candidate-extension back-compat (defaulted fields; no positional construction in
production) and the store-DI pattern are resolved in §2–§3.

## 9. External writes required

**None.** New `tools/discover_for_notebook.py`, an additive extension to `tools/_arxiv_api.py`, a new
`tests/test_discover_for_notebook.py`, and a small `tests/test_arxiv_api.py` addition. The arXiv API
call is the same egress path m2 already owns. Both briefs independently confirm.
`state.external_writes_required = []`.
