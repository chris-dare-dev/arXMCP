# Research Brief — notebook-paper-discovery-m3

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-31T18:25:00Z

---

## In-codebase context

### Design constitution constraints

`notebook-discovery-model.md §2` (verbatim, load-bearing):
> "Discovery is a **deterministic, LLM-free, human-confirmed** flow."
> "Candidates are *proposed* in the operator console; the operator clicks 'Add' to route a paper through the existing `ingest_one_paper` pipeline."
> "No `anthropic` SDK at runtime (CLAUDE.md §4.7)"

`notebook-discovery-model.md §3` (verbatim, load-bearing):
> "**deduplication happens AFTER channel aggregation, not inside each channel.**"
> "Each channel is therefore a pure 'query → raw candidates' function; the orchestrator owns dedup + ranking + the propose step."

This means `tools/discover_for_notebook.py` (m3) is a **single-channel driver**, not the multi-channel orchestrator. At m3, it is BOTH the channel and the caller, so it can own its own dedup — but the design notes the dedup boundary shifts when m4 adds more channels. The implementation should make the dedup logic explicit and isolatable.

`notebook-discovery-model.md §4` (verbatim):
> "No new MCP tool in v1 ... so `EXPECTED_TOOL_SCHEMA_SHA256` and the BP1 prefix stay byte-stable."

`notebook-discovery-model.md §1` (verbatim):
> "`discovery_category` ... enum `{math.AG, math.NT, math-ph, hep-th}` **or empty**; enforced at the route layer ... (`if … raise`, NOT `assert` per CLAUDE.md §4.7)"
> "`description` free text, `max_length=512`, control chars stripped before storage"

CLAUDE.md §4.7 (verbatim):
> "`assert` is BANNED for invariants — Python `-O` strips them. Use `if … raise RuntimeError(…)` instead."
> "No `anthropic` SDK at runtime."

### **CRITICAL GAP — Candidate missing `title` and full `submitted_date` fields**

The m3 brief specifies: "return a ranked candidate list (`paper_id`, **`title`**, `abstract head`, **`submitted date`**)."

The shipped `tools/_arxiv_api.py:Candidate` dataclass (lines 70–88) has:
- `paper_id: str`
- `submitted_year: int` — only the year, NOT a full date
- `n_authors: int`
- `primary_category: str`
- `abstract_head: str`

**`title` is ABSENT from `Candidate`.** The arXiv Atom `<atom:title>` element IS present in every feed entry (verified: it is a required Atom element per RFC 4287) but `parse_atom_feed` never reads it. `submitted_year` gives only `int`, not a date.

**FLAG: The m3 output shape cannot be satisfied by `Candidate` as shipped.** The implementer MUST either:
(a) extend `Candidate` to add `title: str` and `submitted_date: str` fields, OR
(b) define a new `DiscoveryResult` dataclass in `discover_for_notebook.py` that wraps `Candidate` and also parses `<atom:title>` from the same XML.

Option (a) risks a breaking change to `curate_seed.py` consumers (adding fields to a frozen dataclass is additive but requires all constructors to pass the new fields). Option (b) is cleaner isolation — the discovery driver adds its own output type.

### `notebook_papers` paper_id format — dedup alignment confirmed

`server/notebooks_store.py:list_papers()` (line 526) returns `paper_id` as stored — the junction schema at line 22 stores plain `TEXT`. The `add_paper` route (`server/routes/notebooks.py:697`) calls `_arxiv_url_to_paper_id()` which calls `is_valid_arxiv_paper_id()` and strips the version suffix (via `_arxiv_url_to_paper_id`'s regex extraction from the arXiv URL path). `parse_atom_feed` (lines 169–171) strips the version suffix: `paper_id = paper_id.split("v", 1)[0]`. Both paths produce un-versioned IDs (e.g. `2307.01156`). **Dedup format is aligned — no mismatch.**

### egress confirmation

`_fetch_url` (line 202) calls `urllib.request.urlopen` against `ARXIV_API_URL = "https://export.arxiv.org/api/query"` only. No other host. TLS cert verification is on by default (`urllib.request` default). The `MAX_RESPONSE_BYTES = 50 * 1024 * 1024` cap guards against hostile large responses (Threat 7 mitigation). The `contact_email` is passed to `build_user_agent()` for arXiv's polite-pool User-Agent.

### politeness

`fetch_candidates` sleeps `POLITENESS_SLEEP_SECONDS` (= 3s) BETWEEN pages only. For `max_results ≤ 2000` — typical for per-notebook discovery — this is a single request with no sleep. The politeness obligation falls on the m3 driver's choice of `max_results`: if it requests ≤2000 there is no inter-page sleep. The brief's "≥3s politeness preserved" AC is satisfied because the contract is per-page, not per-call, and for typical single-page requests no sleep is required.

---

## Prior decisions and lessons

Git log shows m2 shipped as `feat(tools): reusable arXiv Atom API library` (commit `eb17f1c`) and its adversary finding closed as `rect(tools): close F1 MEDIUM from notebook-paper-discovery-m2 critique` (commit `f396fbf`). The F1 finding concerned `_keyword_clause` returning `None` for blank cleaned values — this is already fixed; `build_query_url` handles `None` clauses correctly.

The `_fetch_url` monkeypatch pattern for tests is established at `tests/test_arxiv_api.py:3`:
> "The HTTP layer is mocked via `monkeypatch.setattr(_arxiv_api, "_fetch_url", …)` — the `graph_ingest._fetch_openalex_work` pattern"

m3 tests must use the same pattern: `monkeypatch.setattr(_arxiv_api, "_fetch_url", stub)`.

`EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py` must NOT change — the brief and design constitution both confirm no new MCP tool.

The `tools/_notebook_common.py` shared-module pattern (leading underscore, `__all__`, `from __future__ import annotations`, `if … raise` invariants) applies to `discover_for_notebook.py` as well.

---

## External sources

The arXiv Atom API `<atom:title>` element is a required Atom feed element per RFC 4287 §4.1.3.1 ("MUST"). Every arXiv Atom entry includes it. The ATOM_NS namespace dict in `_arxiv_api.py` is `{"atom": "http://www.w3.org/2005/Atom", ...}` so the XPath `entry.findtext("atom:title", namespaces=ATOM_NS)` will extract it.

The `<atom:published>` field gives ISO-8601 date string (e.g. `"2023-07-04T18:30:00Z"`). `parse_atom_feed` already reads it for `submitted_year` extraction. The full ISO string is available and should be preserved as-is for the `submitted_date` output field.

No MCP spec changes needed (no new tool). No prompt-caching docs needed (no tool schema change). No new pip dependencies: `defusedxml` is already in the project.

---

## Failure-mode analysis

**(a) Notebook missing or empty `discovery_category`**

Trigger: `discover_for_notebook(slug)` called for a notebook with `discovery_category=""` (m1 allows empty as a valid state meaning "no category declared"). `build_query_url(category="")` raises `ValueError("category must be a non-empty arXiv category code")` (line 127 of `_arxiv_api.py`). The driver must catch this BEFORE calling `fetch_candidates` and return a clean error, not let the `ValueError` propagate as an unhandled exception. Also trigger: slug does not exist — `get_notebook(slug)` returns `None`; the driver must return a clean error. Mitigation: early-exit guards at the top of `discover_for_notebook` — check `get_notebook` result first, then check `discovery_category` non-empty, before any HTTP call.

**(b) All candidates already in notebook (empty dedup result)**

Trigger: every returned paper_id is already in `notebook_papers`. After dedup, the result list is empty. This is a VALID result (not an error); the operator sees "0 new candidates found". The driver should return an empty list `[]` with a log message (INFO level: "all N candidates already in notebook"). Do NOT raise. The AC says "≥1 candidate and 0 already in notebook_papers" for the happy-path test; an all-deduplicated result is a legitimate runtime state.

**(c) Determinism / ordering — same-submittedDate tiebreak**

`fetch_candidates` passes `sortBy=submittedDate&sortOrder=descending` to arXiv. arXiv sorts server-side; the driver receives already-sorted candidates. Dedup must PRESERVE this order (use an order-preserving filter, not set difference). Two papers with the same submitted date and category have an arXiv-server-side secondary sort that is opaque; for the dedup filter, the order is what arXiv returned. For a FIXED mocked API response (the AC's "deterministic" requirement), `_fetch_url` returns the same bytes → `parse_atom_feed` returns the same list → the filter preserves order → output is deterministic. The implementer should use a list comprehension with an `existing_ids` set for O(1) lookup: `[c for c in candidates if c.paper_id not in existing_ids]`.

**(d) Dedup format correctness — versioned vs un-versioned IDs**

As confirmed above: `parse_atom_feed` strips version suffix (`split("v", 1)[0]`); `add_paper` route strips via URL extraction; `list_papers()` returns stored un-versioned IDs. Format is aligned. No mismatch risk. The implementer must build `existing_ids = {row["paper_id"] for row in await store.list_papers(slug)}` — these are already un-versioned.

**(e) Operator-data trust boundary — `description` → `abs_keywords`**

`notebook-discovery-model.md §1`: "control chars stripped before storage" at the route layer. The stored `description` is already sanitized. `_keyword_clause` in `_arxiv_api.py` (line 91–107) strips embedded double-quotes and wraps in double-quotes, neutralizing injection. The driver must NOT re-process the description (e.g. don't strip again or re-quote) — pass `description` directly as `abs_keywords`. Double-processing could corrupt legitimate keyword text (e.g. a description containing `'don\'t'` would have its apostrophe preserved by the existing cleanup but a naïve re-strip might change it). Mitigation: single-layer cleanup, already in m2.

**(f) Politeness on repeated / looped runs**

The driver is a per-notebook synchronous function. For a single notebook it issues ≤1 arXiv page (for typical `max_results ≤ 2000`) with no sleep. If a future caller loops over multiple notebooks, inter-notebook sleep is the caller's responsibility, not the driver's. The driver's contract mirrors `fetch_candidates`: politeness is per-page, not per-notebook. The m3 brief is silent on multi-notebook iteration (m4 is the panel + HTTP route). The implementer need not add inter-notebook sleep in the driver itself; document this in the module docstring.

---

## Recommendation

Implement `tools/discover_for_notebook.py` as a standalone module with a single public function `discover_for_notebook(slug, *, store, max_results=200, contact_email=None, sleep=time.sleep) -> list[DiscoveryResult]`. Define a new `DiscoveryResult` dataclass (NOT extending `Candidate`) with fields `paper_id: str`, `title: str`, `abstract_head: str`, `submitted_date: str`, `primary_category: str`. Parse `<atom:title>` and the full `<atom:published>` string directly in `discover_for_notebook.py` using a thin wrapper around `_arxiv_api._fetch_url` + `defusedxml` — OR extend `parse_atom_feed` to also return title + full date. The cleaner path: extend `Candidate` in `_arxiv_api.py` to add `title: str = ""` and `submitted_date: str = ""` as optional fields (additive, backward-compatible with `as_tsv_row`), parse them in `parse_atom_feed`, and define `DiscoveryResult` in `discover_for_notebook.py` as the public output type constructed from `Candidate` fields. This keeps XML parsing in one place.

Failure guards at the top of the function: check `store.get_notebook(slug)` first (→ `ValueError` if missing); check `discovery_category` non-empty (→ `ValueError`). Return `[]` (not an error) for all-dedup case. Use `[c for c in candidates if c.paper_id not in existing_ids]` (order-preserving). No `assert` anywhere. No `anthropic` SDK. No new pip dep. No MCP tool registration — `EXPECTED_TOOL_SCHEMA_SHA256` unchanged.

---

## Open questions

1. **`Candidate` extension vs new parse path**: extending `Candidate` in `_arxiv_api.py` to add `title` and `submitted_date` is additive but changes a shipped module. The implementer must decide whether to extend `Candidate` (preferred — single XML parse site) or duplicate the feed-parsing logic in `discover_for_notebook.py`. Recommendation above picks extension; confirm there are no callers that construct `Candidate(...)` with positional args that would break (grep shows `curate_seed.py` uses `fetch_candidates` which goes through `parse_atom_feed` — no direct `Candidate(...)` construction in production code, only in tests with keyword args).

2. **`store` dependency injection vs module-global**: the driver needs `NotebooksStore` to call `list_papers`. It should accept `store` as a parameter (not import the global singleton) for testability. The test can pass a mock store. Confirm this is acceptable given the `tools/` module pattern (other `tools/` scripts use a CLI entrypoint that constructs the store).

---

## External writes the implementation will require

None — this milestone is purely local. No git push, no PR, no infra mutation, no third-party API call from agent code.
