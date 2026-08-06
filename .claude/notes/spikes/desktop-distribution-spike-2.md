# ADR: one application-data root spike

**Status:** Accepted for prototype; production migration deferred
**Decision:** Conditional GO
**Date:** 2026-08-06

## Decision

Installed, desktop, and container launches will own one canonical, absolute
`ARXMCP_DATA_DIR`. First-party mutable state and launcher-controlled library
state must stay below it. A frozen typed value object will derive `corpus/`,
`index/{lancedb,kuzu,bm25,sqlite}/`, `notebooks/`, `cache/`, `ops/`, `logs/`,
`backups/`, and `tmp/`; resolution has no writes, while a separate EAFP probe
prepares the tree. Package assets remain read-only and package-relative.

Precedence is explicit root; positively identified source checkout default
`<repo>/var/arxmcp`; installed platform-native default; no implicit container
default. Source mode temporarily accepts a relative root against captured
startup CWD with a deprecation warning. Installed/container mode rejects it.

## Executable evidence

`tests/test_desktop_data_root_spike.py` contains the disposable resolver and
six focused cases. They cover source, simulated installed-wheel, and
container launch fixtures; existing/missing absolute roots; legacy-relative
source roots; spaces and Unicode; root and descendant symlinks;
lexical `..`; and a read-only application beside a writable data root.
Construction leaves missing roots absent. The wheel fixture snapshots its
package and unrelated CWD.
The container fixture places ARXMCP, HF/Transformers, XDG, Matplotlib, HOME,
and all three temp variables below one mount.

## Runtime-write inventory

| Area / mode | Exact remaining owners | Current default or destination |
|---|---|---|
| Server config; installed | `server/config.py:Config`, `server/operator_settings.py:DEFAULT_DB_PATH` | Independent LanceDB, Kuzu, cache, BM25, theorem-name, notebooks, ops, and observational data-root defaults under relative `var/arxmcp` |
| Server stores; installed | `server/main.py:lifespan`, `server/resources.py:Resources.startup`, `{cache_sqlite,notebooks_store,operator_settings,theorem_names_store,paper_metadata_store,documents_store}.py` | SQLite create, WAL/PRAGMA, migration, metadata and document writes |
| Retrieval; installed | `server/retrieval/bm25.py:BM25Phase._sync_startup`, `server/corpus_freshness.py`, `server/corpus_manifest.py` | BM25 auto-build and corpus-version/manifest state under `index/` |
| Notebook UI; installed | `server/routes/notebooks.py`, `server/{ingest_tracker,parse_tracker}.py`, `tools/_notebook_common.py` | Notebook registry/tree, uploads, render scratch, markers, status/log paths; helper currently derives wheel paths beside `site-packages` |
| Library state; installed | `server/model_loader.py`, `server/retrieval/rerank.py`, Starlette multipart, `ingest/textbook_parser.py` | HF/XDG caches, spooled temp, MinerU HOME/cache and per-run temp |
| Spawned ingest; installed | `tools/{notebook_ingest,notebook_pdf_parse,notebook_textbook_ingest,notebook_fetch}.py`; `ingest/{ar5iv_fetch,bulk_ingest,chunker,preamble,embedder,store,bm25_indexer,extract_equations,index_definitions,index_equations,index_theorem_names,ingest_summary,textbook_chunker,textbook_parser,textbook_renderer}.py` | Raw/parsed/chunk/embed data, LanceDB/BM25/SQLite, summaries, failures and scratch |
| Offline ingest | `ingest/{graph_ingest,inspire_ingest,intra_paper_refs,kuzudb_schema,oai_delta,re_embed,embed_equations}.py` | Explicit CLI outputs plus duplicated checkout/CWD-relative corpus, index, checkpoint and ops defaults |
| Offline tools | `tools/{fetch_seed,fetch_one_paper,re_embed_all,recover_preambles,notebook_chunks_backfill,notebook_documents_backfill,notebook_metadata_backfill,notebook_cutover,notebook_init,notebook_purge,notebook_reconcile_marker,notebook_repair_registry,notebook_restore,daily_metrics_report,documents_coverage_report,parser_failures_report,ingest_sentinel,cdm_eval,regen_metrics_fixture,wheel_install_check}.py` | Developer/ingest/build outputs and repo-derived notebook, cache, reports, fixtures and ops paths |
| Shim; installed | `shim/arxmcp_shim.py` | No filesystem writes; protocol bytes only |
| Ops / developer | `ops/{cutover,drift_check,watchdog_eval,checkpoint_notebooks_db,restore_drill_check}.py`, `ops/{cron,systemd}/*`, `Makefile` | Repo-root `var/arxmcp` locks, sentinels, reports, checkpoints and cutover state |
| Intentional external | `ops/backup.sh`, `ops/restore_drill.sh`; CLI output arguments; Lean/lake, CA and MinerU binary inputs | Operator-selected restic repository/restore target or explicit developer output; never silently reclassified as confined app data |

Read-only `server/frontend/`, router YAML, JSON schemas, fixtures, binaries, and
CA bundles are inputs, not writes. Every production owner above remains
unchanged by this spike.

## Compatibility and migration

Retain the names `ARXMCP_LANCEDB_PATH`, `ARXMCP_KUZU_PATH`,
`ARXMCP_CACHE_DB_PATH`, `ARXMCP_BM25_INDEX_ROOT`,
`ARXMCP_THEOREM_NAMES_DB_PATH`, `ARXMCP_NOTEBOOKS_DB_PATH`, and
`ARXMCP_OPS_DIR`. In strict installed mode, canonical alias targets must remain
under the root; arbitrary external aliases are incompatible with a one-root
claim. Trusted offline CLI output flags remain explicit exceptions.

Migration order: production resolver and fixtures; Compose/Docker/K8s explicit
root and matching mount; `Config`; `_notebook_common` and import-time operator
settings; stores/routes/trackers; spawned ingest; model/HOME/XDG/temp launch
environment; write-observing wheel/container gates; offline ingest/tools; then
ops shell and Makefile. Compose currently mounts `/app/var/arxmcp` without
setting the root. K8s redirects HF/XDG but leaves Matplotlib and `/tmp` outside
the PVC. Those manifests must move before an installed fallback changes.

## Boundary and fallback

`Path.resolve(strict=False)` plus `relative_to` catches existing-prefix symlink
escapes and traversal, but not a later local-operator symlink swap; this ADR
does not promise descriptor-relative, no-follow I/O. If platform-native
defaulting cannot be packaged reliably, require an absolute root outside source
mode. If a native dependency still escapes redirected HOME/XDG/temp, launch it
with isolated HOME/cache/temp below the root and a deny-write sandbox. A
NO-GO is required if that fallback cannot contain observed writes; never weaken
the one-root claim silently.
