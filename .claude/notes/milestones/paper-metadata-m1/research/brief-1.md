---
milestone_id: "paper-metadata-m1"
researcher_role: "explore"
injection_attempts: 0
---

# Research brief (explore) — paper-metadata-m1

## Affected files / context

### Current `get_paper` behavior (m2 surface — m1 must not touch it)
- `server/handlers/paper.py` — synthesizes from the LanceDB chunks table only; `authors`/`title`/`abstract`/`year`/`categories` are hard-coded `None`; `metadata_status: "synthesized_from_chunks"`. The byte-cap helper `_cap` is already forward-designed for real abstracts (`enforce_byte_cap(payload, body_text_path=("paper", "abstract"))`). Validates input with `is_valid_arxiv_paper_id`. m1 designs the store this handler will read in m2; m1 itself changes NO handler and NO tool schema.
- Handler behavior tests live in `tests/test_tools_all.py`; security tests reference `handle_get_paper` in `tests/security/test_path_traversal.py`.

### The store pattern to mirror
- `server/notebooks_store.py` — the named pattern: async-over-sync SQLite (`asyncio.to_thread` + `asyncio.Lock`, single `sqlite3.Connection`, WAL), `open()` async classmethod, `PRAGMA user_version` schema versioning with strictly ADDITIVE migrations (v1→v5 precedent; the v4→v5 block shows the required atomic `BEGIN/COMMIT` wrapping when a migration has >1 statement, since the connection is autocommit). Durability tiers are deliberate: `synchronous=FULL` + `fullfsync=ON` for non-regenerable state (notebooks.db); regenerable caches (`server/cache_sqlite.py`, `server/theorem_names_store.py`) stay NORMAL. arXiv metadata is regenerable from the API, so NORMAL is defensible — `theorem_names_store.py` (SQLite index written offline, read by a handler) is the closest structural precedent.
- Central DB: `var/arxmcp/cache/notebooks.db`, currently `user_version=5`, tables `notebooks`, `notebook_papers`, `notebook_ingest_runs`, `operator_settings` (verified live).
- **Storage placement is an open design decision** (roadmap wording supports both):
  - (A) New table(s) keyed `(slug, paper_id)` in notebooks.db via ADDITIVE v5→v6 migration inside `NotebooksStore`. Pro: `NotebooksStore` is already opened in the server lifespan (`server/main.py:470-490`, `app.state.notebooks_store`, wired via `server/mcp_resources.set_notebooks_store`) so m2 wiring is nearly free; matches "notebooks_store.py pattern" literally.
  - (B) Per-notebook SQLite file under `var/arxmcp/notebooks/<slug>/` (mirrors fork-C isolation precedent: `lancedb/`, `index/bm25/`, `cache/retrieval.db` — see `server/config.py:98-163, 458-560`). Matches "per-notebook store" wording; needs a new open path for m2.
- New store module belongs in `server/` (siblings: `notebooks_store.py`, `theorem_names_store.py`, `operator_settings.py`) even though m1's only writer is a CLI.

### CRITICAL: notebook membership source of truth
- The `notebook_papers` junction table is EMPTY for every notebook (verified live: `SELECT slug, COUNT(*) FROM notebook_papers GROUP BY slug` returns no rows). bridgeland-stability IS registered in `notebooks` (kind `arxiv`), but its membership lives ONLY in `var/arxmcp/notebooks/bridgeland-stability/papers.txt`. The backfill driver MUST read papers.txt via `tools/_notebook_common.read_paper_ids_from_papers_txt` (line 228) — keying off the junction table would hydrate zero rows and silently "pass".

### Bridgeland-stability notebook shape (the acceptance target)
- `var/arxmcp/notebooks/bridgeland-stability/`: `papers.txt` (127 uncommented IDs), `lancedb/`, `index/bm25/`, `cache/retrieval.db`, `ops/`, `pending-pdfs.txt`, `queries.json`.
- IDs are mixed new-style (`0708.2247`, `2303.07061`) and old-style (`math/0212237`, `alg-geom/9410026`, `hep-th/0002037`), all unversioned. `hep-th/0403166` is commented out (ar5iv-skipped) — excluded from the denominator. ≥95% of 127 ⇒ ≥121 rows need non-NULL title+authors.

### `tools/_arxiv_api.py` — the Atom client and its gaps for m1
- Has: `build_query_url` (search_query=cat:… only), `parse_atom_feed` (defusedxml; raises on `/api/errors#` error entries and non-XML), `fetch_candidates` (pagination, injectable `sleep`, `POLITENESS_SLEEP_SECONDS=3.0` between pages), `_fetch_url` (private, monkeypatch point; polite User-Agent via `tools.arxiv_fetch.build_user_agent`; 50 MB read cap).
- Gap 1 — **no `id_list` support**. Backfilling specific IDs needs the Atom API `id_list=` parameter; `build_query_url`'s no-keyword output is byte-locked by `TestBuildQueryURL`/`TestCurateQueryURL`, so add a new URL builder rather than changing it.
- Gap 2 — **old-style ID prefix drop** in `parse_atom_feed` (line 189): `paper_id = id_url.rsplit("/", 1)[-1]` turns `http://arxiv.org/abs/math/0212237v1` into `0212237` (archive prefix lost). This directly fails the t-atom-mapper round-trip acceptance; the mapper needs a prefix-preserving extraction (e.g. split on `/abs/`), while leaving `Candidate` semantics stable for `curate_seed`/discovery callers.
- Gap 3 — `Candidate` lacks author NAMES (only `n_authors`), lacks all `<category>` terms (only `arxiv:primary_category`), and only carries the whitespace-normalized summary. A richer metadata record (or extended parse) is needed for title/authors/abstract/year/categories. Precedent for backward-compatible extension: `title`/`submitted_date` were appended with defaults in m3.
- Politeness/email: `tools/_notebook_common.resolve_contact_email` (line 150; chain: explicit → SQLite `operator_settings` → `ARXMCP_CONTACT_EMAIL` → raise) enforced at `run()` entry, never at import (`tools/notebook_fetch.py:80-104` pattern). `ARXMCP_CONTACT_EMAIL` must NOT be set for `make up` (server rejects it) — ingest-shell-only.

### Ingest flow / hook point
- Flow: `tools/notebook_fetch.py run(slug)` (ar5iv HTML + raw tex per papers.txt) → `tools/notebook_ingest.py run(slug)` → `ingest/bulk_ingest.run_bulk_ingest(paper_ids, lancedb_staging_path=…)` (sequential per-paper loop, `ingest/bulk_ingest.py:341`) → per-notebook BM25 build.
- The t-ingest-hook task ("metadata row exists after ingest, no extra operator step") slots most naturally at the tools layer (`notebook_fetch.py` or `notebook_ingest.py`), keeping `ingest/bulk_ingest.py` free of metadata-API network calls. It is `should`-priority; milestone acceptance needs only the backfill driver + cold reopen.
- Backfill CLI conventions (`tools/notebook_*.py`): module-level pure `run(slug) -> int` + argparse `main`, `NotebookError` for operator errors, `validate_slug`, machine-parseable summary line (`fetched=N from_cache=M …` in notebook_fetch).

### Frozen 7-tool schema constraint
- `server/tools.py::ALL_TOOLS` and `tools/list` are byte-stable, pinned by `EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py` (regen only via `--update-tool-schema-hash`); BP1 pinned by `EXPECTED_BP1_SHA256` in `tests/test_prompts.py`. m1 touches neither if it stays out of `server/tools.py`, `server/handlers/`, and `server/prompts.py` — the roadmap KR requires both hashes unchanged.

### Test conventions / surfaces
- HTTP mocking: `monkeypatch.setattr(_arxiv_api, "_fetch_url", …)` with synthetic Atom feed bytes (`tests/test_arxiv_api.py`; the `graph_ingest._fetch_openalex_work` pattern). No live arXiv calls in the suite.
- Store tests: `tmp_path` SQLite; migration-idempotence precedents in `tests/test_checkpoint_notebooks_db.py`, `tests/test_notebook_durability.py`, `tests/test_notebook_restore.py` (these may pin `SCHEMA_VERSION` if option A bumps it — check and update in lockstep).
- CLI tests: `tests/test_notebook_fetch.py` calls `run()` directly with mocked delegates.
- Cold-reopen AC test shape: hydrate → close → reopen → assert metadata served while the chunks table is absent or mocked-to-raise.
- Source discipline: `assert` banned in src (`if … raise`), fine in tests; `ruff check .` clean; full suite via `uv run python -m pytest`. Note: this checkout is on Windows — 29 pre-existing Windows-platform failures are documented in CLAUDE.md §3 and are not regressions.

### Adjacent code that could break
- Option A migration: every test opening `NotebooksStore` re-runs migrations; a non-additive or non-atomic v5→v6 block is the named FM (see v4→v5 crash-loop comment in `notebooks_store.py:260-295`).
- `build_query_url` / `parse_atom_feed` / `Candidate` are shared with `tools/curate_seed.py` and the discovery driver — byte-stability and backward-compat tests exist; extend, don't mutate.
- `tools/notebook_fetch.py` / `notebook_ingest.py` if the ingest hook lands — their tests assert exact summary lines and exit codes.

## Acceptance criteria the implementer must meet

1. (Roadmap AC1) Backfill driver run against bridgeland-stability produces metadata rows with non-NULL `title` AND `authors` for ≥95% of its arxiv-kind paper_ids — denominator is the 127 uncommented papers.txt entries, so ≥121 rows.
2. (Roadmap AC2) After process restart and a cold store reopen, metadata is served without touching the chunks table — proven by a regression test where the chunks table is unavailable/raises on the metadata read path.
3. (t-store-schema) Initializing the store twice against the same file is a no-op; the schema-version row is unchanged on the second run; migrations are additive and atomic.
4. (t-atom-mapper) An Atom entry for an old-style id maps to a record with title/authors/abstract/year/categories populated, and the id round-trips unversioned with its archive prefix intact (`math/0212237v1` → `math/0212237`).
5. (t-backfill-driver) Every arXiv lookup honors the politeness contract (3 s between requests, polite User-Agent with resolved contact email, run-entry email enforcement) and a driver re-run is a no-op (idempotent writes, skip already-hydrated rows).
6. Repo gates: `make test` green with new offline tests (mocked `_fetch_url`), `ruff check .` clean, `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` byte-unchanged, no `assert` in src, no Markdown outside `.claude/` (except subdir READMEs).
7. (t-ingest-hook, should-priority) A paper newly added to a notebook has a metadata row after ingest completes with no extra operator step — legitimate to descope to a follow-up if the slice tightens; AC1/AC2 are the milestone gates.

## Risks and open questions

1. The declared dependency `paper-metadata-spike-1` (Atom field coverage across ID shapes) is `status: planned` and no spike note exists anywhere under `.claude/notes/` — field coverage for old-style/versioned IDs is unvalidated. Design defensively: nullable columns + a per-row status/fetched-at marker rather than assuming full coverage.
2. Storage placement ambiguity (central notebooks.db table vs per-notebook DB file). Both readings are supported by the roadmap text; option A minimizes m2 wiring (store already in lifespan + mcp_resources), option B matches fork-C per-notebook isolation. Implementer must decide and record the rationale.
3. Silent-zero failure mode: `notebook_papers` is empty, so any driver keyed off the junction table hydrates nothing yet exits 0. Membership MUST come from papers.txt, and the driver's summary line should expose the hydrated/total counts so a zero-row run is loud.
4. AC1 requires a live network run against export.arxiv.org (operator action, not CI): with an `id_list` batch endpoint this is ~1–2 requests; without it, 127 requests × 3 s ≈ 6.5 min. Old-style ids inside `id_list` responses still hit the prefix-drop bug (risk item 5) — the two gaps compound.
5. The `parse_atom_feed` old-style prefix drop is pre-existing shared behavior; fixing it in place could shift `curate_seed`/discovery outputs. Safer path: a separate metadata-mapping entry point (new function or richer record) that owns correct id extraction, leaving `Candidate` byte-stable for existing callers.
