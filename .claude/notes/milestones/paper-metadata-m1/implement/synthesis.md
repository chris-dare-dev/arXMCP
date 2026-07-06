# Implement synthesis — paper-metadata-m1

## Built

- **AC1 (≥95% backfill path, proven offline):** `tools/notebook_metadata_backfill.py`
  `run(slug)` reads membership from `var/arxmcp/notebooks/<slug>/papers.txt` via
  `read_paper_ids_from_papers_txt` (tools/notebook_metadata_backfill.py:296), batches
  ≤50 ids per `id_list` request, and upserts prefix-preserved unversioned rows.
  CI proves the full path offline (`tests/test_notebook_metadata_backfill.py::TestHappyPath`),
  including the old-style `math/0212237` round trip into the store. The live run
  against bridgeland-stability (127 uncommented ids) is an operator action:
  `uv run python tools/notebook_metadata_backfill.py bridgeland-stability`
  (~3 requests, ≈6 s + backoffs; requires a contact email via `make init EMAIL=…`).
- **AC2 (cold reopen, no chunks table):** `server/paper_metadata_store.py` is a
  self-contained SQLite store — no LanceDB import on any path.
  `tests/test_paper_metadata_store.py::TestColdReopen` hydrates → closes → reopens
  cold with `lancedb.connect` monkeypatched to raise and no chunks table on disk;
  a structural test pins the absence of `import lancedb`/`server.corpus`/`chunks_table`.
- **t-store-schema:** double-init no-op with unchanged `PRAGMA user_version`
  (`TestStoreSchema::test_double_init_is_noop`); v0→v1 migration is ADDITIVE
  (`CREATE TABLE IF NOT EXISTS`, no DROP anywhere — structurally pinned), atomic
  (explicit BEGIN/COMMIT on the autocommit connection, server/paper_metadata_store.py:150),
  and re-runnable without data loss (`test_migration_is_rerunnable_without_data_loss`).
- **t-atom-mapper:** `tools/_arxiv_api.py::parse_atom_metadata` +
  `extract_paper_id_from_abs_url` split on `/abs/` and strip `v\d+\Z`, so
  `math/0212237v1` → `math/0212237` with title/authors/abstract/year/categories
  populated (`tests/test_arxiv_api_metadata.py::TestParseAtomMetadata::test_old_style_round_trip`).
  The pre-existing `parse_atom_feed` prefix-drop (line 189, `rsplit("/", 1)`) is
  deliberately UNCHANGED — `Candidate` stays byte-stable for `curate_seed`/discovery,
  pinned by `TestLegacyCandidateStability`.
- **t-backfill-driver:** politeness (3 s spacing before every request after the
  first; contact email enforced at `run()` entry via `resolve_contact_email` and
  threaded to `_fetch_url`'s polite UA; 503 backoff through `parse_retry_after`
  clamped so the live-observed `Retry-After: 0` cannot hammer; ≥60 s 429 cool-down;
  retry budget of 3 attempts/request degrading to per-id misses), idempotent re-run
  with ZERO network egress (`TestIdempotency`), loud machine-parseable summary
  (`hydrated= skipped= missing= malformed= total=`) with per-id miss reasons on stderr.
- **Gates:** new/changed test files 43/43 green offline (`_fetch_url` monkeypatched,
  no live arXiv calls); `ruff check .` clean repo-wide; no `assert` in src
  (`if … raise` throughout); `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256`
  byte-unchanged (`tests/test_server_tool_schema.py` + `tests/test_prompts.py`:
  43/43 passed; `server/tools.py`, `server/handlers/`, `server/prompts.py` untouched);
  no Markdown outside `.claude/`.
- **t-ingest-hook: DESCOPED** to a follow-up (should-priority; synthesis §7 names
  descope as legitimate). Rationale: the hook must be best-effort/non-blocking so
  an arXiv outage cannot wedge notebook ingest, which needs its own failure-mode
  design inside `notebook_fetch`/`notebook_ingest` whose tests pin exact summary
  lines and exit codes — bundling it would have grown the diff well past budget.
  The backfill driver is the authoritative repair path in the interim.

## Storage placement decision (research open question 1): OPTION B

One SQLite file per notebook at `var/arxmcp/notebooks/<slug>/paper_metadata.db`
(`PAPER_METADATA_DB_FILENAME`), not a v5→v6 table in central `notebooks.db`:

1. **Durability-tier coherence** — arXiv metadata is regenerable (re-run the
   backfill), so it belongs at `synchronous=NORMAL` (`theorem_names_store`
   precedent), not inside the `FULL`+`fullfsync` non-regenerable notebooks.db.
2. **Fully additive m1** — no `NotebooksStore.SCHEMA_VERSION` bump, no lockstep
   edits to `test_checkpoint_notebooks_db.py` / `test_notebook_durability.py` /
   `test_notebook_restore.py`, zero risk of new failures in existing surfaces.
3. **Fork-C isolation precedent** — membership truth is per-notebook
   (`papers.txt`); `lancedb/`, `index/bm25/`, `cache/retrieval.db` are all
   per-notebook siblings.
4. **Process-boundary safety** — the CLI writer stays off the daemon's live
   central DB; same CLI-writes/server-reads split as the BM25 index.

Cost accepted: m2 must add one open call in the server lifespan (mirroring the
theorem-names store) instead of free-riding on `app.state.notebooks_store`.

## Branching note

All commits on `main` directly, per CLAUDE.md §4.1 ("All work lands on `main`
directly. No feature branches."). No push (per-event authorization, §4.4).
Commits made with `--no-gpg-sign` per the explicit orchestrator dispatch for
this Windows checkout (no signing key present here); flagged for Phase 3/4.

## Files touched

- `server/paper_metadata_store.py` — NEW async-over-sync SQLite store (NORMAL tier).
- `tools/_arxiv_api.py` — ADDITIVE: `build_id_list_url`, `parse_atom_metadata`,
  `PaperMetadata`, `strip_id_version`, `extract_paper_id_from_abs_url`.
- `tools/notebook_metadata_backfill.py` — NEW backfill CLI (`run(slug)` + argparse
  `main`, `NotebookError`, summary-line convention).
- `tests/test_paper_metadata_store.py` — NEW (schema, upsert, cold reopen).
- `tests/test_arxiv_api_metadata.py` — NEW (mapper, URL builder, legacy stability).
- `tests/test_notebook_metadata_backfill.py` — NEW (politeness, idempotency,
  failure modes, membership source).
- `.claude/notes/milestones/paper-metadata-m1/implement/synthesis.md` — this note.

## Deferred

- t-ingest-hook (see above) — follow-up: best-effort hydration in
  `tools/notebook_fetch.py` or `notebook_ingest.py` after the per-paper loop.
- Live backfill run against bridgeland-stability (operator action; AC1 numeric
  coverage to be recorded then). The brief-2 recorded re-run URL should also be
  executed and pasted into the spike note when the API is healthy.
- OAI-PMH `GetRecord` alternative (brief-2) — not needed unless Atom id_list
  proves unreliable in the live run.

## external_writes_required

- `git push origin main` (Phase 4 orchestrator boundary only — copied from brief-2;
  no new external writes introduced: the CLI performs read-only polite GETs to
  export.arxiv.org and writes only under gitignored `var/arxmcp/`)

## Test deltas

- +43 tests across 3 new files (9 store / 20 mapper+builder / 14 driver — 43 total
  as collected); 0 existing tests modified.

## Check gate results

- `uv run ruff check .` (repo-wide): PASS
- `uv run python -m pytest tests/test_paper_metadata_store.py
  tests/test_arxiv_api_metadata.py tests/test_notebook_metadata_backfill.py`: PASS (43/43)
- Hash pins: `tests/test_server_tool_schema.py` + `tests/test_prompts.py`: PASS (43/43)
- Adjacent spot-check (`test_arxiv_api.py`, `test_arxiv_fetch.py`, `test_fetch_seed.py`,
  `test_identifiers.py`, `test_discover_for_notebook.py`, `test_discover_route.py`,
  `test_m3_cli.py`, `test_notebook_fetch.py`, `test_notebook_durability.py`,
  `test_checkpoint_notebooks_db.py`, `test_notebook_restore.py`, `test_make_targets.py`,
  `test_operator_settings.py`): PASS except 3 PRE-EXISTING environment failures,
  none touched by this diff:
  - `test_arxiv_fetch.py::TestUserAgent::{test_builds_from_env,test_missing_email_raises}`
    — this workstation's `var/arxmcp/cache/notebooks.db` has a persisted
    `operator_settings.contact_email` (`cedare96@gmail.com`) which wins over the
    monkeypatched env var by design (onboarding-uplift-m2 D1). Fails on any
    checkout with a persisted email; my diff imports nothing in that chain.
  - `test_operator_settings.py::TestDefaults::test_default_db_path_matches_var_arxmcp_cache`
    — Windows path-separator assertion (`var\arxmcp\…` vs `var/arxmcp/…`), one of
    the CLAUDE.md §3 documented Windows-platform failure classes.
- `make test` full run: SKIP on this checkout (29 documented pre-existing
  Windows-platform failures make the full suite red by baseline; gate per
  dispatch = new tests green + ruff clean + no NEW failures, verified above).
- git status: clean of implementation files (the ~50 pre-existing user-WIP dirty
  files were never staged or reverted).
