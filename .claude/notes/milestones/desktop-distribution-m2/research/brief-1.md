---
milestone_id: "desktop-distribution-m2"
researcher_role: "explore"
injection_attempts: 0
---

# Research brief (explore) — desktop-distribution-m2

## Affected files / context

Implement m2 as consumer wiring plus an observed installed-wheel gate; keep
`server.application_paths.ApplicationPaths` as the only derivation owner. A
single `Config.application_paths` instance should be passed to live server
consumers instead of letting routes/resources independently re-resolve ambient
environment at import time. The full wheel smoke should start the real console
script, exercise each named writer, and reject every observed mutation outside
the chosen root.

- `server/application_paths.py:15-33,92-194` already owns the immutable layout,
  strict installed-mode alias confinement, platform default, and explicit
  `prepare()` probe. Preserve source `<repo>/var/arxmcp`, canonical
  `index/kuzu`, and the distinction between pure resolution and filesystem
  preparation. Do not add another root resolver.
- `server/config.py:568-605` resolves once and rebinds LanceDB, Kùzu, retrieval
  cache, BM25, theorem-name, notebook-registry, and ops fields. Existing tests
  at `tests/test_application_paths.py:37-150` pin all retained aliases, including
  the intentional rule that trusted source-mode aliases may remain external
  while installed aliases may not escape the root.
- `server/main.py:477-559` correctly opens `NotebooksStore` at
  `config.notebooks_db_path`, but the rest of the daemon still has parallel path
  sources. `server/resources.py:1525-1666` calls
  `notebook_lancedb_path(slug)` without the configured notebook base;
  `server/routes/notebooks.py:63-73,363,1295-1345` and
  `server/routes/ui.py:40-47,152-167` consume import-time notebook/corpus
  globals; and `server/mcp_resources.py:113-123,216-223` does the same. Pass
  `config.application_paths.notebooks`, `.corpus`, and `.notebooks_db` through
  request/resource dependencies. Avoid a mutable process-global “rebind paths”
  hook, which would cross-contaminate multiple `create_app(Config(...))` test
  instances.
- `tools/_notebook_common.py:30-44,82-150` is a compatibility seam: its globals
  now come from `ApplicationPaths.resolve()`, and its helpers already accept a
  `base=` argument. Keep source/offline defaults, slug validation, symlink
  rejection, and containment; production server callers should supply the
  live Config base explicitly.
- `server/corpus_manifest.py:538-553` is a concrete installed-mode defect:
  production defaults `settings_db_path` directly to legacy-relative
  `operator_settings.DEFAULT_DB_PATH`, bypassing the call-time resolver at
  `server/operator_settings.py:106-111`. `server.mcp_resources` must provide
  the canonical notebook base and settings DB. Add a regression to
  `tests/test_corpus_manifest.py` / `tests/test_mcp_resources.py` that would
  otherwise read `cwd/var/arxmcp/cache/notebooks.db`.
- `tools/wheel_install_check.py:378-488` already installs real dependencies,
  verifies `server.__file__` is in the child venv, launches from an unrelated
  CWD with an absolute `ARXMCP_DATA_DIR`, and polls `/healthz`. Its log currently
  lands at `tmp_cwd/server-boot.log` (`:424-433`), directly contradicting the
  smoke's write-confinement AC, and it inherits nearly the whole parent
  environment (`:410-421`). Move capture to `<root>/logs/server-boot.log`, strip
  ambient `ARXMCP_*`, Python/dynamic-loader variables, and redirect HOME,
  HF/XDG/Matplotlib/temp state beneath the root before importing the app.
- Bootstrap health alone is not writer coverage: `Resources.startup()` returns
  before LanceDB, BM25, and `RetrievalCache.open()` when no marker exists
  (`server/resources.py:499-537`), while the lifespan only creates the notebook
  registry. Extend the same smoke to POST a notebook through `/ui/api/notebooks`,
  then run wheel-installed writer code for
  `RetrievalCache.open(config.cache_db_path, corpus_version=1)`,
  `operator_settings.set_setting(..., config.notebooks_db_path)`, and
  `ingest.store.write_corpus_version_marker(config.lancedb_path, ...)`.
  Assert the exact artifacts are respectively under `notebooks/`,
  `cache/retrieval.db`, `cache/notebooks.db`, `index/lancedb/`, and `logs/`.
- Add cheap always-on confinement tests around the writer probe (recommended
  `tests/test_installed_write_confinement.py`) and extend
  `tests/test_wheel_packaging.py:390-417` for the opt-in real wheel run. Snapshot
  an unrelated CWD and the installed application/package tree before and after;
  on POSIX, making the application tree read-only is an additional guard. The
  child must import only the wheel, with no `PYTHONPATH` or checkout path.
- `docker/Dockerfile.server:126-172` and `infra/docker-compose.yml:40-87`
  currently mount `/app/var/arxmcp` but set no `ARXMCP_DATA_DIR`. Behavior works
  only because `WORKDIR /app`, a copied source tree, and `python -m server.main`
  let the source package shadow the installed wheel. Pin
  `ARXMCP_DATA_DIR=/app/var/arxmcp` to the matching mount in the image and
  Compose, and extend `tests/test_compose_server.py`. Check the sibling K8s
  ConfigMap/mount contract (`infra/k8s/configmap.yaml`,
  `tests/test_k8s_manifests.py`) so the same image is not deployment-dependent.
- Load-bearing constraints remain unchanged: server logs are structured stdout
  (the smoke/supervisor owns its capture file); package assets stay read-only and
  package-relative; the loopback-only bind remains; no MCP tool changes means no
  `EXPECTED_TOOL_SCHEMA_SHA256` re-pin; do not add `assert`,
  `BaseHTTPMiddleware`, the runtime `anthropic` SDK, or model-name strings in
  `server/`; preserve `kuzu==0.11.3` and
  `tests/conftest.py`'s `KMP_DUPLICATE_LIB_OK=TRUE` guard.

## Acceptance criteria the implementer must meet

1. Build/install the wheel into an isolated venv, launch installed
   `arxmcp-server` from an unrelated CWD with a temporary absolute data root and
   bootstrap mode, prove the imported `server` is the wheel copy, and receive
   HTTP 200 from `/healthz`.
2. In that same relocation run, create a notebook through the live REST route
   and exercise the real retrieval-cache, operator-settings, corpus-marker, and
   log-capture writers; record their paths and prove every resolved path and
   every newly observed entry is beneath the root.
3. Snapshot/protect the unrelated CWD and installed application tree and fail on
   any mutation there. Keep an always-on subprocess regression that simulates
   installed mode from two CWDs and exercises the same writers, so `make test`
   catches CWD/repository-derived defaults without requiring a 2 GB wheel build.
4. Thread the one `Config.application_paths` instance through notebook routes,
   per-notebook retrieval, MCP resources, and corpus-manifest settings reads;
   production code must not fall back to import-time legacy globals when Config
   supplies the path.
5. Preserve source `make up` / `make up-wizard` behavior and all seven retained
   per-store aliases, including source external-alias compatibility and strict
   installed confinement. Pin Docker/Compose (and the sibling K8s deployment)
   to the absolute data root matching their writable mount.
6. Run focused path/route/resource/manifest/packaging tests, the real full wheel
   relocation check, and the canonical `make test` gate with Ruff clean. Do not
   change the seven-tool schema or prompt-cache hashes.

## Risks and open questions

1. A `/healthz`-only success is a false confinement proof because bootstrap mode
   skips retrieval cache and corpus-marker writers. The explicit post-health
   writer probe above is required; do not relabel `notebooks.db` as all five
   requested write classes.
2. “Log write” must not turn the server into a file-logging service. Preserve
   12-factor stdout and have the relocation harness (future supervisor boundary)
   capture stdout/stderr at `ApplicationPaths.logs`.
3. Replacing route globals can fan out across a 2,785-line module and many tests.
   Prefer explicit `base=`/path parameters fed by FastAPI dependencies and MCP
   resource wiring; do not introduce mutable singleton path rebinding.
4. Container compatibility is currently accidental source shadowing. Set the
   explicit root before relying on installed imports, and statically assert the
   environment target equals the declared mount target.
5. The existing resolver documents construction-time containment, not
   descriptor-relative no-follow safety against a later local symlink swap.
   Keep that TOCTOU boundary explicit; m2 should not claim or absorb a filesystem
   sandbox. No blocking open question remains for implementation.
