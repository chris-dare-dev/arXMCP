# proof-verify-handler-wiring-m7 — implementation summary

## One-line summary

Notebook persistence layer + 6-route REST CRUD under `/ui/api`
backed by a NEW separate SQLite file at `var/arxmcp/cache/notebooks.db`,
with a `SecFetchSiteMiddleware` `exempt_prefixes=("/ui",)` carve-out
so same-origin htmx posts pass while the MCP surface continues
rejecting same-origin.

## Commit range

`3b43a46..<HEAD-after-feat-commit>`. Base SHA recorded in
`state.json::implementation_base`.

## Acceptance criteria status

From the milestone brief at
`plans/proof-verify-handler-wiring-roadmap.md:302-318`:

- [x] **AC #1** — `POST /ui/api/notebooks {"slug":"bridgeland"}`
  creates a SQLite row AND an on-disk directory at
  `var/arxmcp/notebooks/bridgeland/` (idempotent via
  `mkdir(parents=True, exist_ok=True)`). Duplicate slug returns
  HTTP 409 (`sqlite3.IntegrityError` caught + translated).
  Verified by `TestNotebookCrud::{test_create_notebook,
  test_create_makes_on_disk_directory, test_duplicate_slug_returns_409}`.
- [x] **AC #2** — `POST /ui/api/notebooks/bridgeland/papers
  {"arxiv_url": "..."}` normalizes URL via the new
  `_arxiv_url_to_paper_id()` helper (host whitelist of
  `arxiv.org` + `/abs/` path prefix + `is_valid_paper_id`
  post-validation per m1 rect F3 `\Z` hardening), inserts a
  junction row. Verified by `TestPaperAdd::{test_add_paper_happy_path,
  test_add_paper_with_version_suffix, test_add_paper_old_style_id,
  test_add_paper_with_malformed_url_returns_422,
  test_add_duplicate_paper_returns_409, test_add_paper_to_missing_notebook_returns_404}`.
- [x] **AC #3** — `DELETE /ui/api/notebooks/bridgeland` drops the
  SQLite row + cascades junction rows (via `ON DELETE CASCADE` +
  `PRAGMA foreign_keys = ON`) but **leaves the on-disk directory
  intact**. Subsequent POST with the same slug succeeds. Verified by
  `TestNotebookCrud::test_delete_metadata_only_leaves_dir`,
  `TestForeignKeyCascade::test_delete_notebook_cascades_papers`,
  `TestPostAfterDelete::test_can_recreate_slug_after_delete`.
- [x] **AC #4** — `SecFetchSiteMiddleware` exempts `/ui/*`.
  Verified by `TestMcpStillRejectsSameOrigin::test_mcp_path_rejects_same_origin`
  (existing /mcp behavior preserved — 403 on same-origin),
  `TestUiCarveoutAcceptsSameOrigin::test_ui_api_path_accepts_same_origin`
  (the carve-out fires on `/ui/api/notebooks`), and
  `TestPrefixVsSubstring::{test_uioother_path_not_exempt,
  test_evil_ui_path_not_exempt}` (FM-3 closure — prefix-not-substring
  matching enforced).
- [x] **AC #5** — `EXPECTED_TOOL_SCHEMA_SHA256` unchanged. The
  existing `tests/test_server_tool_schema.py` continues to pass with
  no re-pinning. No modifications to `server/tools.py::ALL_TOOLS`
  (verified by inspection — the diff doesn't touch `tools.py` other
  than the m2-era comment, and no new `ToolMeta` instances ship in
  m7).
- [x] **AC #6** — `make test` green: **2355 passed**, 9 skipped, 1
  xfailed (net +59 over the m4-complete 2296 baseline). Ruff clean.

## New / changed files

- **NEW:** `server/notebooks_store.py` (~270 LOC) — `NotebooksStore`
  class (asyncio.to_thread + asyncio.Lock + WAL + foreign_keys ON
  + schema_version migration).
- **NEW:** `server/routes/notebooks.py` (~410 LOC) — 6 FastAPI
  routes + `_arxiv_url_to_paper_id` helper + `_now_iso` test seam.
- **EDIT:** `server/middleware.py` — `SecFetchSiteMiddleware.__init__`
  now takes `exempt_prefixes: tuple[str, ...] = ()` (backward compat
  preserved); `__call__` checks the prefix list before the
  Sec-Fetch-Site header check.
- **EDIT:** `server/main.py` — opens `NotebooksStore` in `lifespan`
  (attached to `app.state.notebooks_store`), closes it in the
  finally block; registers the router; wires
  `SecFetchSiteMiddleware(exempt_prefixes=("/ui",))`.
- **EDIT:** `server/config.py` — adds
  `notebooks_db_path: Path = Path("var/arxmcp/cache/notebooks.db")`.
- **NEW:** `tests/test_notebook_api.py` (~445 LOC, 44 tests).
- **NEW:** `tests/security/test_sec_fetch_site_carveout.py`
  (~190 LOC, 15 tests).
- **EDIT:** `.claude/docs/security-threat-model-coverage.md` —
  extended the Threat 5 section to cite the m7 carve-out + the new
  test file (so the threat-coverage invariant test sees it).
- **EDIT:** `CHANGES.md` — `## Unreleased` entry for 2026-05-22 m7.

## Tests

`make test`: **2355 passed, 9 skipped, 1 xfailed.**
Net delta from m4-complete: **+59 tests** (44 API + 15 carve-out).
Ruff clean. `EXPECTED_TOOL_SCHEMA_SHA256` unchanged.

## External writes required

**None.** Phase 4 has no blocking external-write gates. The
implementation creates (on first server startup against this code):
- `var/arxmcp/cache/notebooks.db` (SQLite, gitignored).
- `var/arxmcp/notebooks/<slug>/` directories on POST (gitignored).

Both are local filesystem mutations; no external API calls fire.

## Deviations from the brief

- **DB file location is `var/arxmcp/cache/notebooks.db`**, not the
  `var/arxmcp/notebooks/notebooks.db` that R-1 initially proposed.
  Synthesis D1 ruled in favor of R-2's location because the brief
  says verbatim "sibling to `cache_db_path`" — and to avoid
  entangling the metadata store with per-notebook on-disk dirs
  (which `tools/notebook_purge.py` may mass-delete).
- **6 routes** rather than the brief's loose "GET/POST/DELETE at
  two levels" (which could be interpreted as 4 routes total or 6
  depending on how you count). Synthesis D2 resolved that DELETE on
  the papers junction is single-row (`/papers/{paper_id}` with
  `{paper_id:path}` syntax for old-style IDs containing slashes).
  Collection-level papers DELETE ("delete all papers in notebook
  X") would be operator-destructive without an explicit flag — out
  of m7 scope; m9's ingest-trigger work could surface it later.
- **arxiv URL host whitelist is `arxiv.org` only** for m7. R-1
  proposed handling both `arxiv.org/abs/` AND
  `ar5iv.labs.arxiv.org/html/`; synthesis D3 deferred ar5iv to m8
  (the m8 brief explicitly mentions paste-form `ar5iv.labs.arxiv.org/html/`
  as in-scope there). m7's normalizer is minimal — `m8` can extend
  it one-line.
- **NotebooksStore lives in `app.state.notebooks_store`**, NOT
  attached to `Resources`. Synthesis D5 chose the cleaner separation
  so the HTTP-only UI surface doesn't entangle with the ML-resource
  lifecycle (`Resources` owns BGE-M3 + LanceDB + embed semaphore).
- **`_arxiv_url_to_paper_id` returns `2604.26204` (not None) for
  `https://arxiv.org/abs/2604.26204\n`** — Python's
  `urllib.parse.urlparse` strips ASCII control characters from URLs
  before parsing. The m1-rect-F3 hardening on `is_valid_paper_id`
  still protects against trailing-newline attacks on RAW paper IDs
  (defense-in-depth), but at the URL layer the newline is already
  neutralized. Pinned by
  `TestArxivUrlNormalizer::test_trailing_newline_in_url_is_stripped_by_urlparse`
  so a future urllib change would surface here.
- **`# noqa: B008` on each `Depends(...)` line** — `B008` flags
  function calls in default-arg position. FastAPI's standard DI
  pattern (`store: NotebooksStore = Depends(get_notebooks_store)`)
  is the canonical exception. The alternative `Annotated[...,
  Depends(...)]` form would avoid the lint but is verbose. The
  project's existing pattern is to suppress the lint at the use site.

## What this unblocks

m8 (htmx + Jinja2 UI) can now build its frontend against the live
REST routes — no server-side stubs needed. m9 (ingest trigger +
status polling) reads from the same `NotebooksStore` (importable
from `server/notebooks_store.py` directly) when wiring the
background ingest task.

The chain of m7 → m8 → m9 is the Track-D frontend that turns
arXMCP from a CLI-only tool into a browser-pasteable workflow for
the downstream `/proof-verify` consumer.
