---
milestone_id: desktop-distribution-spike-2
researcher_role: explore
injection_attempts: 0
---

# Research Brief — desktop-distribution-spike-2

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-08-06T11:53:56Z

## In-codebase context

The spike should return **GO, conditional on strict installed-mode containment and
launcher-owned third-party cache/temp redirects**.

Load-bearing constitution constraints are: “Local-first. No paid cloud services in
the critical path.” and “Single source of truth for the corpus”
(`01-mission-and-context.md`); “Never mutate in place. No manual symlink swaps.”
(`02-architecture-overview.md`); “Configuration via environment variables
(12-factor).” (`06-mcp-server-design.md`); and “LLM-generated tool inputs and
adversarial arXiv content can do unintended things to my workstation.”
(`08-security-observability-ops.md`). The resolver must also preserve
`01-mission-and-context.md`'s “Determinism over cleverness. Every byte the MCP
server returns must be reproducible bit-for-bit across calls.”

**Conflict — the brief cannot simultaneously preserve arbitrary legacy per-store
paths and guarantee one root.** `server/config.py:93-176,406-415` exposes
`ARXMCP_LANCEDB_PATH`, `KUZU_PATH`, `CACHE_DB_PATH`, `BM25_INDEX_ROOT`,
`THEOREM_NAMES_DB_PATH`, `NOTEBOOKS_DB_PATH`, and `OPS_DIR` independently;
`ARXMCP_DATA_DIR` currently controls only disk metrics/pause-sentinel behavior.
An override such as `ARXMCP_CACHE_DB_PATH=/tmp/x.db` necessarily escapes another
configured root. Preserve the names and in-root values, but reject out-of-root
values in installed/desktop mode. Source/offline legacy mode may warn and retain
them during migration.

### Authoritative write/default inventory

| Class | Writes and current defaults | Installed? |
|---|---|---|
| Server stores | `NotebooksStore.open` (`server/main.py:550-553`) creates/migrates `cache/notebooks.db`; `RetrievalCache.open` (`server/resources.py:866-871`) creates `cache/retrieval.db`; existing theorem-name and paper-metadata SQLite files may run PRAGMAs/migrations. `operator_settings.py:91,218-239` separately captures the notebooks DB default at import time. | Yes |
| Retrieval/index | `BM25Phase._sync_startup` (`server/retrieval/bm25.py:451-467`) auto-builds missing `index/bm25/vN/{chunk_ids.json,bm25.pkl}`; `ingest/bm25_indexer.py:104-105` still has repo-derived index and stats globals. Kùzu opens its canonical `index/kuzu` path (not `kuzudb`); LanceDB opens below `index/lancedb`. | Yes |
| Notebook UI | `server/routes/notebooks.py:363-428,1173-1202,1910-2041` creates notebook directories, uploads HTML/PDF atomically, rewrites corpus markers, creates MinerU scratch/render output, and updates SQLite. All derive through `tools/_notebook_common.py:30-41`, whose “repo root” becomes site-packages in a wheel: a read-only-application write bug. | Yes |
| Spawned ingest | `server/ingest_tracker.py:232-239` launches `tools.notebook_ingest`; it writes notebook LanceDB/BM25/ops, while `bulk_ingest` also writes repo-derived ar5iv cache, parsed HTML, chunks, embeddings, global stats, and `ops/ingest-summary.json` (`ingest/ar5iv_fetch.py`, `chunker.py`, `embedder.py`, `store.py`). | Yes |
| Third-party/scratch | Transformers writes `$HF_HOME` or `~/.cache/huggingface` (`server/model_loader.py:124-132`; reranker equivalent). Starlette spools multipart files over 1 MiB through `tempfile.SpooledTemporaryFile`. MinerU confines `TMPDIR` to notebook output but deliberately inherits `HOME`, hence `~/.cache/mineru` (`ingest/textbook_parser.py:62-96,260-291`). | Yes |
| Offline ingest/tools | `ingest/{preamble,chunker,embedder,store,ar5iv_fetch,bulk_ingest,oai_delta,re_embed,graph_ingest,inspire_ingest,intra_paper_refs}.py` and notebook/fetch/backfill/report tools duplicate checkout-root or CWD-relative corpus/index/cache/ops defaults. These are packaged, but most are operator/developer CLIs rather than daemon flow. | Migrate after installed path |
| Ops/build/deploy | `ops/cutover.py`, watchdog/drift/report tools and every cron lock/status path except delta's pause flag hard-code repo `var/arxmcp`; `Makefile:109-121` bootstraps it. Docker declares `/app/var/arxmcp`, Compose mounts the whole tree, but neither sets `ARXMCP_DATA_DIR` or HF/XDG/temp redirects. K8s redirects HF/XDG to the PVC but leaves `MPLCONFIGDIR` and `/tmp` outside it. Restic repository and restore destination are intentional external operator targets. | Ops/dev; manifests are compatibility fixtures |
| Shim | `shim/arxmcp_shim.py` writes only protocol bytes to stdout; it owns no files. | Yes; already clean |

`pyproject.toml:40-76` deliberately ships `server/`, `ingest/`, `tools/`, `shim/`,
and `ops/`, so package-relative constants in any of them matter. The existing wheel
boot (`tools/wheel_install_check.py:378-488`) sets an absolute data root but neither
redirects the independent defaults/caches nor asserts that package and CWD stayed
unchanged.

Read-only package assets under `server/frontend/`, Lean/lake binaries, CA bundles,
`ARXMCP_MINERU_BIN`, and the external `RESTIC_REPOSITORY` are inputs or explicit
operator destinations, not application-state children.

## Affected files / context

- Prototype and ADR: `tests/test_desktop_data_root_spike.py` and
  `.claude/notes/spikes/desktop-distribution-spike-2.md`.
- Root/config seams: `server/config.py`, future `server/application_paths.py`,
  `tools/_notebook_common.py`, and `server/operator_settings.py`.
- Installed writers: `server/{main,resources,health,ingest_tracker,parse_tracker}.py`,
  `server/routes/notebooks.py`, and the SQLite store modules.
- Spawned ingest: `tools/notebook_ingest.py` plus the repo-derived defaults in
  `ingest/{ar5iv_fetch,bulk_ingest,chunker,embedder,store,bm25_indexer}.py`.
- Compatibility fixtures: `tools/wheel_install_check.py`, `tests/conftest.py`,
  `Makefile`, `docker/Dockerfile.server`, `infra/docker-compose.yml`, K8s manifests,
  and the repo-root defaults in remaining `ingest/`, `tools/`, and `ops/` writers.

## Prior decisions and lessons

`git log -20` begins with `d4cc1d9 chore(notes): checkpoint desktop m1 research`.
The adjacent m1 synthesis is deliberately blocked on this spike and already chose
a frozen typed owner. E14_S05 adversary F2 proved that independently-derived shell
and Python sentinel paths disagree when `ARXMCP_DATA_DIR` changes. Notebook
retrieval's prior cache bug likewise proves LanceDB, Tier-1 cache, and BM25 must
move as one substrate, not piecemeal.

Tests currently patch each static global independently in `tests/conftest.py:231-305,
340-415`; preserve explicit injection while replacing import-time defaults with
call-time delegates. Do not remove the load-bearing
`KMP_DUPLICATE_LIB_OK=TRUE` guard there. Preserve `kuzu==0.11.3` and
`var/arxmcp/index/kuzu/`. Use no invariant `assert`, `BaseHTTPMiddleware`, runtime
`anthropic` SDK, or forked code. This spike changes no MCP tool or prompt, so do
not re-pin `EXPECTED_TOOL_SCHEMA_SHA256`, BP1, or BP2 hashes. New Markdown belongs
under `.claude/`; `AGENTS.md`'s `.Codex/` paths are stale doc drift against the live
tree and `CLAUDE.md`.

## External sources

None. The parent task is explicitly codebase-only; this spike does not change the
MCP surface or prompt caching, so external protocol/vendor documentation is not
needed.

## Acceptance criteria the implementer must meet

1. **Spike AC1 — inventory:** retain a checked inventory across `server/`,
   `ingest/`, `tools/`, `shim/`, and `ops/`, explicitly classifying daemon/spawned
   installed writes versus offline developer, ingest, and operator destinations.
2. **Spike AC2 — prototype:** exercise one frozen typed `ARXMCP_DATA_DIR` resolver
   against source-checkout, installed-wheel, Docker/Compose, and K8s fixtures without
   wiring it into production consumers.
3. **Spike AC3 — containment:** prove deterministic handling of absolute, relative,
   missing, read-only, symlink, whitespace, and Unicode roots, including rejection of
   `..` and descendant-symlink escape and no writes beside a read-only application.
4. **Spike AC4 — compatibility:** record every retained alias, strict installed-mode
   precedence, migration order, and remaining exact call-site group; demonstrate that
   arbitrary out-of-root per-store compatibility is intentionally unavailable.
5. **Spike AC5 — decision:** write the ADR with GO/NO-GO, evidence from the fixtures,
   and the isolated-HOME/XDG/temp plus deny-write-sandbox fallback.

## Recommendation

Implement the smallest disposable proof as a frozen, slotted `ApplicationPaths`
prototype local to `tests/test_desktop_data_root_spike.py`, then record results in
`.claude/notes/spikes/desktop-distribution-spike-2.md`. Precedence must be:

1. Source checkout, env unset: canonical `<repo>/var/arxmcp` (never current CWD).
2. Installed/container: require an absolute `ARXMCP_DATA_DIR`; fail clearly when
   absent or relative. The desktop supervisor and container manifests always set it.
3. Derive typed `corpus`, `index/{lancedb,kuzu,bm25,sqlite}`, `notebooks`, `cache`,
   `ops`, `logs`, `backups`, and `tmp`; construction is pure, and a separate
   `prepare()` creates/probes directories using EAFP rather than `os.access()`.

Table-test absolute/missing roots; source-relative compatibility; installed-relative
rejection; whitespace and Unicode acceptance; root-symlink canonicalization;
descendant-symlink and `..` escape rejection; and a chmod-read-only fake app location
with every observed mutation under a separate root. The wheel fixture should run
from an unrelated CWD and snapshot both CWD and installed package before/after.
The container fixture should assert one mount plus `ARXMCP_DATA_DIR`, `HF_HOME`,
`TRANSFORMERS_CACHE`, `XDG_CACHE_HOME`, `MPLCONFIGDIR`, `TMPDIR`, `TEMP`, and `TMP`
below it. Give MinerU an app-root HOME/cache while retaining its per-invocation temp.

Migration order: resolver/fixture → Config defaults → `_notebook_common` and
`operator_settings` aliases → server resources/routes and tracker redaction (replace
the hard-coded `var/arxmcp` regexes in `server/{ingest,parse}_tracker.py`) → spawned
ingest context → model/temp launcher env → Docker/Compose/K8s → offline ingest/tools
→ ops shell/Makefile. Fallback if a native dependency still writes elsewhere:
launch with isolated `HOME`/XDG/temp below the root and a deny-write sandbox; do not
weaken the one-root ADR silently.

## Risks and open questions

- **Legacy-path risk:** independent per-store overrides can escape the root; installed
  mode must reject them when out of root.
- **Library-write risk:** HF/XDG caches, Starlette multipart spool files, and MinerU's
  inherited HOME bypass first-party derivation unless the launcher redirects them.
- **Compatibility risk:** changing an installed or container fallback without setting
  an explicit absolute root can silently move state away from the expected mount.
- **Symlink risk:** validation proves construction-time containment, not every later
  writer's TOCTOU safety; do not claim descriptor-relative no-follow I/O in this spike.

No open questions — implementation can proceed on the recommendation above.

## External writes the implementation will require

| type | target | why |
|---|---|---|
| git push | `origin/main` | Publish the completed spike commits, only after per-event authorization. |
| GitHub issue mutation | `chris-dare-dev/arXMCP#385` | Mark the spike complete/link its ADR, only after explicit authorization. |
