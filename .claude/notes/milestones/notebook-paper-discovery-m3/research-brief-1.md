# Research Brief — notebook-paper-discovery-m3

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-31T18:30:00Z

---

## In-codebase context

### `tools/_arxiv_api.py` — full read (m2 output)

**`Candidate` dataclass** (`_arxiv_api.py:69–88`):
```python
@dataclass(frozen=True)
class Candidate:
    paper_id: str
    submitted_year: int
    n_authors: int
    primary_category: str
    abstract_head: str
```
No `title` field. `submitted_year` is an `int` (year only), not a full date string.

**`build_query_url` signature** (`_arxiv_api.py:110–147`):
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

**`fetch_candidates` signature** (`_arxiv_api.py:216–263`):
```python
def fetch_candidates(
    category: str,
    max_results: int,
    contact_email: str | None = None,
    *,
    abs_keywords: str | None = None,
    ti_keywords: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Candidate]:
```

**`parse_atom_feed`** (`_arxiv_api.py:150–199`) reads: `atom:id`, `atom:published`
(year only), `atom:author` (count), `arxiv:primary_category`, `atom:summary`
(as `abstract_head`). It does **NOT** read `atom:title`. The `published` ISO-8601
string is parsed for year only; the raw date string is discarded after `.year` is
extracted (`_arxiv_api.py:176–179`).

**`_fetch_url`** (`_arxiv_api.py:202–213`) — private, monkeypatch target for tests:
```python
def _fetch_url(url: str, contact_email: str | None = None) -> bytes:
```
User-Agent is built via `build_user_agent(contact_email)` from `tools.arxiv_fetch`.

### Critical gap: `title` and full `submitted_date` missing from `Candidate`

The AC requires the driver to return `(paper_id, title, abstract head, submitted date)`.
The Atom feed entry has `<title>` as a sibling of `<published>` and `<summary>` in the
`atom:` namespace — it is already present in every entry `parse_atom_feed` iterates.
The raw `published` ISO-8601 string (e.g. `"2023-07-04T18:30:00Z"`) is available
in the loop at `_arxiv_api.py:173–179` but is currently discarded after extracting
`.year`.

**Resolution (see Recommendation):** extend `Candidate` and `parse_atom_feed` in
`_arxiv_api.py` to add `title: str` and `submitted_date: str` (raw ISO-8601 from
`<published>`). This is additive — no existing field is removed, the dataclass is
`frozen=True` so callers using positional construction will break (but there are none;
all existing instantiation is keyword-based inside `parse_atom_feed` itself). The
existing `submitted_year: int` field is retained for backward compatibility with the
`as_tsv_row` method and `curate_seed.py` callers.

### `server/notebooks_store.py` — `get_notebook` and `list_papers`

**`get_notebook`** (`notebooks_store.py:349–378`):
```python
async def get_notebook(self, slug: str) -> dict[str, str] | None:
    # returns dict with keys:
    # slug, display_name, lancedb_path, created_at, notebook_kind,
    # parse_status, parse_error, parsed_html_path,
    # discovery_category, description
```
Returns `None` if the slug is absent. Both `discovery_category` and `description`
are present post-m1 (SCHEMA_VERSION 5).

**`list_papers`** (`notebooks_store.py:516–531`):
```python
async def list_papers(self, slug: str) -> list[dict[str, str]]:
    # returns [{"paper_id": r[0], "added_at": r[1]}, ...]
    # ordered added_at DESC, paper_id ASC
    # returns [] for an unknown slug (callers check get_notebook first)
```

**`NotebooksStore.open`** (`notebooks_store.py:108–299`) — async classmethod:
```python
@classmethod
async def open(cls, db_path: Path) -> NotebooksStore:
```

### How existing tools resolve db_path and run async

`tools/notebook_init.py:180–197` shows the canonical async pattern:
```python
from server.notebooks_store import NotebooksStore
async def _register() -> bool:
    store = await NotebooksStore.open(db_path)
    try:
        await store.create_notebook(...)
        return True
    except _sqlite3.IntegrityError:
        return False
    finally:
        await store.close()
inserted = asyncio.run(_register())
```

`tools/notebook_list_offline.py` uses a different pattern: raw `sqlite3` read-only
`mode=ro` URI, no `NotebooksStore`. The offline-lister deliberately avoids
`NotebooksStore.open` to prevent running migrations. For the **discover driver**,
we need `list_papers` which is only on `NotebooksStore`, so the `asyncio.run`
pattern from `notebook_init.py` is the right model.

The db_path is resolved via `server.operator_settings.DEFAULT_DB_PATH`:
```python
# server/operator_settings.py:91
DEFAULT_DB_PATH: Path = Path("var/arxmcp/cache/notebooks.db")
```
All tools import this as the default: `from server.operator_settings import DEFAULT_DB_PATH`.

### `notebook-discovery-model.md` — load-bearing constraints

From §2 (propose→confirm):
> "The discovery driver issues official-API queries (arXiv Atom in m2; Semantic Scholar /
> OpenAlex in m3; local citation-graph in m4), deduplicates, and returns a ranked
> candidate list. No `anthropic` SDK at runtime (CLAUDE.md §4.7)."

From §3 (channel-dedup boundary, CC-3):
> "deduplication happens AFTER channel aggregation, not inside each channel. … Each
> channel is therefore a pure 'query → raw candidates' function; the orchestrator owns
> dedup + ranking + the propose step."

This means m3's driver is the arXiv-Atom channel only. It returns raw candidates after
deduplicating against the notebook's existing `notebook_papers` junction — this is the
**within-channel dedup against persisted papers** (not against other channels). The
post-aggregation cross-channel dedup boundary in §3 applies to m4+ when channels are
run in parallel; m3 is single-channel so within-channel dedup is correct here.

From §1 (field schema):
> "An empty `discovery_category` means 'no category declared' and MUST never be
> rejected (FM-1)."
> "`description` carries the free-text topic/keywords. It is the `abs:`/`ti:` keyword
> source for the keyword channel."

From §2 (no MCP tool):
> "No new MCP tool in v1. … `EXPECTED_TOOL_SCHEMA_SHA256` and the BP1 prefix stay
> byte-stable."

**Consequence:** m3 does NOT add any tool to `server/tools.py`. No schema re-pin needed.

### `_validate_discovery_category` (route layer)

`server/routes/notebooks.py:193–207`:
```python
_VALID_DISCOVERY_CATEGORIES: frozenset[str] = frozenset(
    {"math.AG", "math.NT", "math-ph", "hep-th"}
)

def _validate_discovery_category(value: str) -> None:
    # empty string is accepted (FM-1)
    # non-empty non-member raises NotebookError
```
The driver must replicate this logic: if `discovery_category == ""`, raise
`ValueError("notebook has no discovery_category set")` (or return empty list — see
Recommendation). Do NOT `import` the route-layer function in a CLI tool (wrong direction;
the valid set is small enough to re-state or centralize).

---

## Prior decisions and lessons

**Recent git log** (last 20 commits):
- `0569759` — finalize notebook-paper-discovery-m2 state -> complete
- `f396fbf` — close F1 MEDIUM from m2 critique (blank keyword clause fix)
- `eb17f1c` — reusable arXiv Atom API library (m2)
- `9956c41` — finalize notebook-paper-discovery-m1 state -> complete
- `1c45e51` — close F1 MEDIUM from m1 critique
- `e48e44d` — feat: notebook topic metadata + discovery-model note (m1)

m1 and m2 are both confirmed SHIPPED. No adjacent milestone state problems.

**m2 rect F1** (`f396fbf`) fixed the blank-keyword-clause bug: `_keyword_clause`
returns `None` when the value is empty after stripping. The driver MUST pass
`description` as `abs_keywords` — blank descriptions produce no abs clause, which
is correct (falls back to category-only query).

**HTTP-mock pattern** (from `tests/test_arxiv_api.py:132–156`):
```python
monkeypatch.setattr(_arxiv_api, "_fetch_url",
    lambda url, contact_email=None: _feed(200))
```
The m3 test file should monkeypatch `_arxiv_api._fetch_url` the same way.

**NotebooksStore test pattern** (from `tests/test_notebook_api.py`): tests that
need a real `NotebooksStore` open a fresh SQLite at `tmp_path / "notebooks.db"` via
`asyncio.new_event_loop().run_until_complete(NotebooksStore.open(db_path))`. The
discover-driver tests should use `asyncio.run` with a `tmp_path` fixture for store
creation and pre-seeding of junction rows for the dedup test.

**`notebook_list_offline.py` anti-pattern warning:** that module deliberately avoids
`NotebooksStore.open` (read-only access, no migrations). The discover driver needs
both `get_notebook` AND `list_papers`, so it must go through `NotebooksStore.open`
+ `asyncio.run` per the `notebook_init.py` pattern.

**No new `assert` usage**: CLAUDE.md §4.7 bans `assert` for invariants. The driver
must use `if … raise ValueError/RuntimeError` for all precondition checks. The m2
library already follows this (confirmed at `_arxiv_api.py:233–234`).

**`_notebook_common.py` slug validation** is the first-line defense. The driver's
`main()` MUST call `validate_slug(slug)` before any path construction or DB access.

---

## External sources

**arXiv Atom `<title>` element:** The arXiv Atom feed (https://export.arxiv.org/api/query)
includes `<title>` as a sibling of `<published>` and `<summary>` inside each `<entry>`.
The `parse_atom_feed` loop already iterates `atom:entry` elements; adding
`entry.findtext("atom:title", default="", namespaces=ATOM_NS)` captures the title.
The `<published>` ISO-8601 string (already read at `_arxiv_api.py:173`) is discarded
after `.year` extraction — retaining the raw string alongside `submitted_year` is
additive.

**Four target arXiv categories** (CLAUDE.md §2): `math.AG`, `math.NT`, `math-ph`,
`hep-th`. These match `_VALID_DISCOVERY_CATEGORIES` in the route layer exactly.

**arXiv API rate-limiting:** `tools/arxiv_fetch.py` sets `POLITENESS_SLEEP_SECONDS = 3.0`.
The `fetch_candidates` sleep parameter honours this between pages. Single-page fetches
(max_results ≤ 2000) have no sleep — correct; the inter-call gap is the caller's
responsibility (the driver returns a list, not a generator, so the caller decides when
to call again).

**MCP spec / prompt-caching docs:** Not relevant — m3 adds no MCP tool and no
server-side cache interaction.

---

## Recommendation

**Extend `Candidate` in `_arxiv_api.py` (option a).** Add two fields:
```python
title: str
submitted_date: str   # raw ISO-8601 from <published>, e.g. "2023-07-04T18:30:00Z"
```
Retain `submitted_year: int` for backward compat with `as_tsv_row` and curate_seed.
Update `parse_atom_feed` to extract `entry.findtext("atom:title", default="", namespaces=ATOM_NS)`
and keep the raw `published` string before discarding it. The `Candidate` dataclass
is `frozen=True` with all construction inside `parse_atom_feed` itself — no external
construction sites to update. This keeps the discovery model's output shape in the
canonical dataclass rather than a second bespoke struct, so m4 channels also benefit.

**Driver signature and structure:**
```python
# tools/discover_for_notebook.py
@dataclass(frozen=True)
class DiscoveryCandidate:
    paper_id: str
    title: str
    abstract_head: str
    submitted_date: str

def discover_for_notebook(
    slug: str,
    *,
    max_results: int = 200,
    contact_email: str | None = None,
    db_path: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[DiscoveryCandidate]:
```

Wait — given the recommendation to extend `Candidate`, the driver can simply return
`list[Candidate]` (already has `paper_id`, `title`, `abstract_head`, `submitted_date`
after the extension). A separate `DiscoveryCandidate` dataclass is unnecessary
duplication. Return `list[Candidate]` directly and let consumers access `.title` and
`.submitted_date`.

**Exact recommended driver signature:**
```python
def discover_for_notebook(
    slug: str,
    *,
    max_results: int = 200,
    contact_email: str | None = None,
    db_path: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Candidate]:
```

**Empty `discovery_category` handling:** raise `ValueError("notebook '{slug}' has no
discovery_category set — run PATCH /ui/api/notebooks/{slug}/topic first")`. An empty
list would silently succeed and confuse the operator. An explicit error is better UX
and allows the caller to distinguish "ran and found nothing" from "was not configured".
Return-empty is the correct response for "no papers found after query + dedup"; raise
is the correct response for "not configured".

**Async vs sync:** The driver is synchronous (`def discover_for_notebook(...)`), using
`asyncio.run(...)` internally to open `NotebooksStore`. This matches the `notebook_init.py`
pattern and keeps the CLI entry point free of event-loop ceremony. The arXiv fetch is
already synchronous (stdlib `urllib`).

**Dedup:** build a `set` of known paper_ids from `list_papers(slug)`, then filter
`fetch_candidates(...)` results removing any candidate whose `paper_id` is in the set.
Order the survivors by `submitted_date DESC` (arXiv API already returns `sortBy=submittedDate
sortOrder=descending` — so the order from `fetch_candidates` is already the correct order
and no re-sort is needed). Determinism is guaranteed because: (1) the API returns
deterministic order for a fixed query, (2) the dedup set operation preserves original
order when filtering sequentially, (3) the mock fixture gives a fixed response.

**CLI entry:** `main()` parses `slug` positionally + optional `--max-results`, `--email`,
`--db-path`. Calls `discover_for_notebook(...)`, prints one TSV row per candidate (or
JSON with `--json`). Exit 0 always; errors print to stderr + exit 1.

---

## Open questions

1. **`as_tsv_row` backward compat after extending `Candidate`:** `as_tsv_row` at
   `_arxiv_api.py:79–88` prints 5 columns (paper_id, year, n_authors, category,
   abstract_head). Adding fields to the frozen dataclass does not break this method.
   Confirm that `tests/test_arxiv_api.py` does not assert on `Candidate.__annotations__`
   or field count directly — a quick grep shows no such assertion; safe.

2. **`submitted_date` field naming:** the raw `<published>` string is the submission
   date (arXiv uses `<published>` for initial submission, `<updated>` for revisions).
   The field name `submitted_date` is accurate. No conflict with the existing
   `submitted_year` name.

3. **Max-results default:** 200 matches `curate_seed.py`'s default and covers typical
   operator use (a notebook has dozens to low hundreds of candidate papers). The
   upstream `fetch_candidates` accepts up to 30,000; the driver's 200 default is
   a sensible operator-facing cap. Implementer may choose 100 if they prefer a faster
   default.

These are minor implementation details; they do not block proceeding. The core
approach is unambiguous.

**No open questions that block implementation.**

---

## External writes the implementation will require

None — this milestone is purely local. `tools/discover_for_notebook.py` is a local
CLI tool; the arXiv API call is the same egress path m2 already owns and was
authorized when m2 shipped. No git push, PR, ticket, or infra mutation is needed
beyond the normal three-commit-per-milestone pattern executed by the implementer.
