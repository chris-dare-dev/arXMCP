# Implementation summary — notebook-paper-discovery-m3

**One-line:** Added `tools/discover_for_notebook.py` — the arXiv-Atom discovery driver
that reads a notebook's topic (m1), queries `_arxiv_api` (m2), dedups against the
notebook's papers, and returns a ranked `DiscoveryCandidate` list; extended
`_arxiv_api.Candidate` with `title` + `submitted_date` to feed the AC output shape.

**Commit range:** `<BASE>..<HEAD>` (filled at commit; implementation_base in state.json).
**Implementation path:** INLINE — 4 files (driver + arxiv extension + 2 test files).

---

## Acceptance criteria status

- [x] **Given a notebook (`discovery_category=math.AG`, keywords "Bridgeland stability"), the driver returns ≥1 candidate and 0 papers already in `notebook_papers`.** `discover_for_notebook_async` reads `discovery_category` + `description` (m1), calls `fetch_candidates(category, max_results, abs_keywords=description)`, and filters out paper_ids already in `notebook_papers` (order-preserving). Regression: `tests/test_discover_for_notebook.py::TestDiscoverHappyPath::test_returns_new_and_dedups_existing` (seeds a notebook with a paper that is also in the mocked feed; asserts it is deduped and ≥1 remains).
- [x] **Requests hit only official arXiv endpoints; the ≥3s politeness contract is preserved.** The driver reaches arXiv only through `_arxiv_api` (only `export.arxiv.org`, TLS, `MAX_RESPONSE_BYTES` cap, polite User-Agent, per-page sleep). Regression: `test_single_page_no_sleep` (one `_fetch_url` call, `sleep` not called for `max_results≤2000`). No new egress host.
- [x] **Output is deterministic given a fixed mocked API response (stable ordering).** arXiv `sortBy=submittedDate desc` order is preserved through the order-preserving dedup filter. Regression: `TestDiscoverHappyPath::test_deterministic_across_calls` (two calls → identical ordered output).
- [x] **Unit tests mock the HTTP layer; no live network calls in CI.** All tests monkeypatch `_arxiv_api._fetch_url` (the m2/graph_ingest pattern) and run the async core against a real `NotebooksStore` on a `tmp_path` SQLite.

## Design decisions (from the synthesis)
- **`_arxiv_api.Candidate` extended** with `title: str = ""` + `submitted_date: str = ""` (defaulted, appended) — the `<title>` (required Atom element) and raw `<published>` ISO string were already in the feed but discarded. Additive: `as_tsv_row`, curate_seed, and all existing keyword constructions are unaffected; `parse_atom_feed` is the only construction site. Regression: `tests/test_arxiv_api.py::TestParseAtomFeed::test_extracts_title_and_submitted_date` + `test_missing_title_defaults_empty`.
- **Driver-owned `DiscoveryCandidate`** `(paper_id, title, abstract_head, submitted_date)` — the AC's exact shape and a stable m4 contract, decoupled from arXiv-internal `Candidate` fields. Mapped from the extended Candidate (XML parsing stays once in `_arxiv_api`).
- **Async core + sync wrapper:** `discover_for_notebook_async(store, slug, …)` takes an injected store (testable); `discover_for_notebook(slug, db_path=…, …)` opens the store and `asyncio.run`s the core (CLI-friendly, the `notebook_init.py` pattern).
- **Guards (no `assert`, §4.7):** unknown slug → `ValueError("not found")`; empty `discovery_category` → `ValueError` BEFORE any HTTP call ("not configured" ≠ "found nothing"); all-deduped → `[]`. Regression: `TestDiscoverGuards` (3 tests incl. `test_empty_category_does_not_call_arxiv`).
- **Keywords flow:** `description` passed unmodified as `abs_keywords` (m2 quotes + strips; no re-processing). Regression: `TestDiscoverQuery::test_keywords_flow_into_quoted_abs_clause` (asserts `cat:math.AG AND abs:"Bridgeland stability"`) + `test_blank_description_is_category_only`.

## Files changed
| File | Change |
|---|---|
| `tools/_arxiv_api.py` | `Candidate` += `title`/`submitted_date` (defaulted); `parse_atom_feed` populates them |
| `tools/discover_for_notebook.py` | NEW — `DiscoveryCandidate`, async core + sync wrapper + CLI `main()` |
| `tests/test_discover_for_notebook.py` | NEW — 9 tests (happy/dedup/determinism/guards/query/egress) |
| `tests/test_arxiv_api.py` | +2 tests for the title/date parse extension |

## New / changed tests
`tests/test_discover_for_notebook.py` (9); `tests/test_arxiv_api.py` (+2). `test_fetch_seed.py` + existing `test_arxiv_api.py` pass unchanged (the new Candidate fields are defaulted).

## Security / constraints
No MCP tool (`EXPECTED_TOOL_SCHEMA_SHA256` + BP1 unchanged); egress unchanged (arXiv via `_arxiv_api`); dedup is read-only against operator data; no `assert`; no `anthropic` SDK (LLM-free); no new pip dep; Markdown only under `.claude/`.

## Deviations from the brief
- The brief's output `(paper_id, title, abstract head, submitted date)` is delivered via a driver-owned `DiscoveryCandidate` (not raw `list[Candidate]`) — same fields, cleaner m4 contract. Required extending `_arxiv_api.Candidate` (additive) to capture `title`/`submitted_date`.

## External writes required
**None.** New driver + an additive `_arxiv_api` extension + two test files. The arXiv API call is the same egress path m2 already owns. `state.external_writes_required = []`.
