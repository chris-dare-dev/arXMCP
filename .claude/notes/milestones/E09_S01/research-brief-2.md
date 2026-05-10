# E09_S01 Research Brief 2 — Kùzu schema + OpenAlex bulk ingest

## 1. In-codebase context

**Design notes that apply (cite by filename):**
- `05-storage-and-indexing.md` § Kùzu citation graph — canonical source.
- `03-ingestion-pipeline.md` § Source 5 (OpenAlex) and § "What gets stored on disk".
- `08-security-observability-ops.md` § Threat 7 (source ingestion fetches).
- `10-references-and-prior-art.md` (OpenAlex / Kùzu URLs and one-liner facts).

**Load-bearing constraints (verbatim quotes):**

> `05-storage-and-indexing.md` ships a *different and richer* schema than the
> brief: `CREATE NODE TABLE Paper (paper_id STRING PRIMARY KEY, title STRING,
> arxiv_categories STRING[], submitted_date DATE, withdrawn BOOLEAN);` plus
> `Author`, `Theorem` node tables and `CITES`/`AUTHORED`/`PROVES`/`NAMED_AFTER`
> rel tables. The `CITES` rel table uses `source ENUM('inspire', 'openalex',
> 'tex_extracted')` and a `citation_count INT` field — **not** the
> `STRING` + `confidence FLOAT` shape in the brief. **Conflict — flag.**

> `03-ingestion-pipeline.md` § Source 5: "Polite pool: include
> `mailto=owner@example.com` query parameter or header to get higher
> limits." (Note: the brief says "mailto: in the User-Agent header"; the
> design note allows either header *or* query-string. OpenAlex docs prefer
> the query parameter and `User-Agent` is reserved by OpenAlex for the
> client identifier.)

> `03-ingestion-pipeline.md` § "What gets stored on disk": disk path is
> `var/arxmcp/index/kuzu/citations.kuzu` — **not** `var/arxmcp/index/kuzudb/`
> as the brief says. Same disagreement in `08-security-observability-ops.md`
> ("Kùzu graph: `/var/arxmcp/index/kuzu/`"). **Conflict — flag.**

> `.gitignore` lines 23-24: `# Build / runtime artifacts (paths anticipated
> by the design notes)` / `/var/arxmcp/`. Production data dir is gitignored;
> tests **must** use `tmp_path`.

**Existing code patterns the implementation must reuse, not reinvent:**
- `tools/arxiv_fetch.py` is the canonical politeness-contract module:
  `build_user_agent(contact_email)` reads `ARXMCP_CONTACT_EMAIL`,
  `validate_paper_id`, `parse_retry_after`, `politeness_sleep`,
  `MAX_RESPONSE_BYTES = 200 * 1024 * 1024`. The pattern is **stdlib
  `urllib.request` only** — no `httpx`, `requests`, or `aiohttp` is in
  `pyproject.toml`. Stay on stdlib. Reuse `build_user_agent` (the format
  string `"arXMCP/0.1 (mailto:{email})"` is the standard).
- `tools/fetch_seed.py` is the canonical CLI/checkpoint pattern: per-loop
  log re-write after every paper for crash-recoverable state, idempotency
  via "already done?" probe at start of loop, `KeyboardInterrupt` writes a
  partial log and returns 130. Mirror this discipline for OpenAlex.
- `tests/test_arxiv_fetch.py`: unit tests for the offline-testable surface;
  HTTP fetch is exercised live, **not** mocked. There is **no** `responses`,
  `httpx_mock`, or `requests_mock` library in `pyproject.toml`. Mocking
  pattern in the codebase is `monkeypatch.setattr` on the module's
  `urllib.request.urlopen`. Use that.
- `tests/conftest.py`: every disk-writing module (LanceDB store stats, BM25
  index root, cache DB) is auto-redirected into `tmp_path` via an
  `autouse=True` `monkeypatch.setattr` fixture (lines 159-234). Add a
  parallel `_patched_kuzu_path` fixture so `var/arxmcp/index/kuzu/` is
  redirected; otherwise every test pollutes the developer's checkout.
- `tools/seed-papers.txt` is the source-of-truth for the 50 seed IDs (see
  E01_S03 commit `tools/curate_seed.py`). Each line is a paper ID; `#` and
  blanks are comments. Reuse `read_seed_list` from `tools/fetch_seed.py`
  rather than re-reading.
- `pyproject.toml` § `[tool.setuptools] packages = ["server", "ingest",
  "tools", "shim"]`. New `ingest/graph_ingest.py` and
  `ingest/kuzudb_schema.py` must live under `ingest/`. CLI invocation
  `python -m ingest.graph_ingest` matches existing convention.
- `var/arxmcp/ops/` already used by `seed.log`, `store-stats.jsonl`,
  `bm25-stats.jsonl`. Putting the checkpoint at
  `var/arxmcp/ops/graph-ingest-checkpoint.json` is consistent.

**Pytest markers** (from `pyproject.toml`): `requires_model` and `eval`.
There is no `requires_network` marker — but **no test in CI ever hits the
network**, period. The pattern is "mock or skip-when-env-unset", not
"mark-and-skip". The integration test must mock.

## 2. Prior decisions and lessons

- E01_S02/E01_S03 (recent, in-tree `tools/arxiv_fetch.py`): explicit
  `noqa: S310` on every `urllib.request` call (fixed-host bandit
  exemption). Use the same noqa for OpenAlex.
- HTTP retry/backoff is **manual + stdlib**: `urllib.error.HTTPError.code
  == 503` triggers `parse_retry_after(headers["Retry-After"], default)`
  followed by exponential backoff (`DEFAULT_503_BACKOFF_SECONDS=30.0`,
  cap `MAX_503_BACKOFF_SECONDS=300.0`). Mirror this for OpenAlex 429s.
- Checkpoint pattern in `tools/fetch_seed.py`: **rewrite the entire
  log/state file after every unit of work** rather than append. Brief asks
  for "every batch of 100 papers"; the existing pattern would say "after
  every paper" — pick the brief's batch=100 since it's an explicit AC, but
  do an atomic write (`tmp + rename`) so a crash mid-write doesn't corrupt
  the checkpoint.
- Threat 7 (`08-security-observability-ops.md`): TLS verify on, no cert
  pinning required for OpenAlex (only arxiv.org/ar5iv mention pinning),
  `MAX_RESPONSE_BYTES = 200 MB` cap on responses. OpenAlex `/works` JSON
  responses are ~10 KB per work; the cap is a paranoia floor.
- No `responses` / `requests_mock` is in deps. Mock by `monkeypatch.setattr`
  on the OpenAlex client function (e.g. patch a `_fetch_work` helper that
  the script defines, returning a fixture dict). This is the same shape
  used by `tests/test_server_startup.py` for HTTP mocking.
- `KMP_DUPLICATE_LIB_OK=TRUE` is set at conftest module load (lines 36-38)
  for `faiss-cpu` + `torch` OpenMP coexistence on macOS. Importing `kuzu`
  alongside these is untested — flag as a smoke-test item.

## 3. External sources

**Kùzu Python bindings (latest stable at brief authoring window 2026-05):**
- PyPI package: `kuzu`. As of late 2025/early 2026 the 0.x → 0.7+/0.8 line
  is the stable channel; the project did **not** yet ship 1.0 GA in 2025.
  Pin a tested minor: `kuzu>=0.7,<0.8` is the conservative choice
  (matches the brief's risk note: "Pin the Kùzu version in
  `pyproject.toml` and include a note that the Cypher dialect may differ
  from Neo4j Cypher").
- API shape: `db = kuzu.Database(path); conn = kuzu.Connection(db);
  conn.execute("CREATE NODE TABLE ...")`. Idempotency is achieved via
  `CREATE NODE TABLE IF NOT EXISTS papers (...)` (Kùzu supports
  `IF NOT EXISTS` since 0.4). Schema introspection: `CALL show_tables()
  RETURN *;` — use this instead of catching exceptions.
- Breaking-change watchlist: `kuzu.Database(path, buffer_pool_size=...)`
  signature changed in 0.5; `QueryResult.get_next()` API stabilized in
  0.6. Test against the pinned minor only.

**OpenAlex API:**
- Endpoint: `https://api.openalex.org/works`.
- Polite pool: per OpenAlex docs, identification can be by `mailto` query
  parameter OR `User-Agent` header containing the email. The docs
  explicitly recommend `?mailto=owner@example.com` as the canonical form.
  Recommend: send **both** `User-Agent: arXMCP/0.1 (mailto:...)` (matches
  brief's AC verbatim) AND `?mailto=...` query string (matches
  `03-ingestion-pipeline.md` § Source 5). Cost: zero. AC stays satisfied.
- Filter syntax: `?filter=concepts.id:C66938386,primary_topic.field.id:fields/mathematics`
  (comma = AND). Concept C66938386 = algebraic geometry; C15736585 =
  number theory. Note: OpenAlex deprecated `concepts` in favor of `topics`
  in mid-2024 — `concepts.id` still resolves but the canonical filter is
  now `topics.id`. Stick with `concepts.id` per the brief and document the
  deprecation as a future migration.
- Pagination: cursor-based via `cursor=*` for first page, then
  `meta.next_cursor` for subsequent pages. Page size: `per-page=200`
  (max). **Do not use `page=N`** — that's deep-pagination via offset and
  is throttled / capped at 10 000 results. The brief says "tens of
  thousands of papers"; cursor pagination is mandatory.
- Rate limit: 10 req/s in polite pool; 100 000 req/day. Cursor pagination
  at 200/page = 50 pages for 10 k results = 5 s wall clock. Under budget.
- `referenced_works` field: per `https://api.openalex.org/works/W...`
  schema, it is `list[str]` of OpenAlex Work URLs (e.g.
  `"https://openalex.org/W2741809807"`), **not** arXiv IDs. Confirmed.
- arXiv ID → OpenAlex Work mapping: OpenAlex exposes
  `?filter=ids.openalex:W...` and `?filter=ids.doi:...` and
  `?filter=ids.pmid:...`, plus a generic
  `?filter=locations.source.id:S4306400194` (the arXiv "source"). For
  per-paper lookup the canonical pattern is
  `https://api.openalex.org/works/https://arxiv.org/abs/<paper_id>` —
  OpenAlex resolves arXiv URLs as identifiers. There is also
  `?filter=ids.openalex:...` and `?search=...` but those are weaker. Use
  the URL-as-ID resolution; it returns one work or 404.
- Reverse mapping (oa_work_id → arxiv_id) for writing scoped `cites`
  edges: each `Work` returned has an `ids` object with `openalex`, `doi`,
  `mag`, `pmid` keys; the arXiv ID is in `ids.arxiv` (e.g.
  `"https://arxiv.org/abs/2307.01156"`) when the work originated on
  arXiv. **Two-pass approach:** (a) for each corpus arXiv ID, fetch and
  cache the work and store `(arxiv_id, oa_work_id)` mapping; (b) when
  walking `referenced_works`, look up the OA work ID in that mapping and
  only emit a `cites` edge if it's present (= "in the corpus"). For
  Tier-3 (tens of thousands), the mapping fits trivially in memory.

## Open questions

- **OA → arXiv reverse mapping mechanism**: resolved above — use the
  `ids.arxiv` field on each Work record, plus an in-memory
  `oa_work_id → arxiv_id` dict built from the per-corpus-paper lookups.
  Implementer should confirm `ids.arxiv` is consistently populated for
  arXiv-originated works (spot-check 10 records).
- **Corpus arXiv paper with no OpenAlex match**: brief confirms — add as
  `papers` node with `oa_work_id=NULL`, no `cites` edges. No further
  question.
- **Source-of-truth for the 50 seed papers**: `tools/seed-papers.txt`,
  read via `read_seed_list()` from `tools/fetch_seed.py`. No env var, no
  manifest needed.
- **`var/arxmcp/` gitignored**: yes (`.gitignore` line 24:
  `/var/arxmcp/`). Test fixtures **must** use `tmp_path` and
  `monkeypatch`; no production-path writes in tests. Add an autouse
  fixture in `tests/conftest.py` that redirects the Kùzu path the same
  way the BM25 / cache / store paths are redirected.
- **`kuzudb_schema.py` as library vs. CLI**: ship as **both**. Module
  exposes `apply_schema(path: Path) -> None` (idempotent via `CREATE …
  IF NOT EXISTS`); module-level `if __name__ == "__main__":` is a thin
  argparse wrapper. `graph_ingest.py` calls `apply_schema()` directly
  before any insert. This matches `ingest/store.py` / `ingest/bm25_indexer.py`
  shape (importable + has CLI). Confirmed by codebase convention.
- **AC says "50 seed papers", brief says "Tier-3 tens of thousands"**:
  the AC is a *Tier-3 deliverable scoped down to the seed for testability*.
  The script must support both: take `--seed-file tools/seed-papers.txt`
  as the default (Tier-3 testable now) and also take
  `--category math.AG math.NT` as the bulk-discovery path (Tier-3 full).
  Integration test runs the seed-file path with mocked OA responses.
  The category-bulk path is exercise-only; not required to pass any AC.
- **Schema disagreement**: brief schema (`papers` lowercase, `STRING`
  fields, `confidence FLOAT`) **conflicts** with `05-storage-and-indexing.md`
  schema (`Paper` titlecase, typed columns, `citation_count INT`,
  ENUM-source, plus `Author`/`Theorem`/`AUTHORED`/`PROVES`/`NAMED_AFTER`).
  Implementer must pick one. **Recommend: follow the brief verbatim** for
  this milestone (it's the latest spec and the AC text references the
  brief's column names) and open a follow-up to either update the design
  note or extend the schema in E09_S02/S03. Do not silently merge.
- **Path disagreement**: brief says `var/arxmcp/index/kuzudb/`; design
  notes say `var/arxmcp/index/kuzu/`. **Recommend: follow the brief**
  (`kuzudb/`) since it's the explicit AC; update the design notes in the
  same PR.
- **`mailto` placement**: brief says User-Agent header; design note
  allows query-string. Recommend sending both, satisfying both.

## External writes the implementation will require

| type | target | why |
|---|---|---|
| dependency-add | `pyproject.toml` runtime deps | add `kuzu>=0.7,<0.8` (pin per brief risk note) |
| live-API-call | `https://api.openalex.org/works/...` | only when an operator runs the CLI manually (not in CI). Tests mock. Polite-pool compliance via `User-Agent` + `?mailto=` |
| disk-write | `var/arxmcp/index/kuzudb/` (operator machine) | initialized Kùzu DB; gitignored, not committed |
| disk-write | `var/arxmcp/ops/graph-ingest-checkpoint.json` (operator machine) | per-batch checkpoint state; gitignored |

No PRs, tickets, or third-party-service writes. CI never hits the network.
