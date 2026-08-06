---
milestone_id: "desktop-distribution-m2"
research_mode: "standard"
research_briefs:
  - "research/brief-1.md"
  - "research/brief-2.md"
external_writes_required:
  - "git push origin main"
estimated_diff:
  loc: "450-700"
  files: "8-12"
  novel_architecture: false
implementation_path: "delegated"
---

# Research synthesis — desktop-distribution-m2

## Recommended implementation

Keep `server.application_paths.ApplicationPaths` as the sole path-derivation
authority. Thread the `Config.application_paths` instance into installed server
consumers that still use import-time notebook, corpus, or settings defaults,
then extend the existing full-wheel installation check with an observed writer
probe. The probe must invoke production writers through the wheel-installed
interpreter and compare filesystem manifests so confinement is demonstrated by
actual mutations, not by resolved path strings or `/healthz` alone.

Preserve structured server logging to stdout. The wheel harness owns its
stdout/stderr capture beneath the temporary application's `logs/` directory;
m2 does not introduce routine file logging.

## Affected files

- `server/application_paths.py` — retain the centralized path contract and
  installed-mode containment rules; change only if a missing canonical child
  path is proven.
- `server/config.py` — continue resolving one immutable path layout and retain
  all seven per-store compatibility aliases.
- `server/main.py` / `server/resources.py` — pass configured notebook/corpus
  paths into live resources rather than re-resolving ambient defaults.
- `server/routes/notebooks.py`, `server/routes/ui.py`, and
  `server/mcp_resources.py` — replace installed-runtime reliance on import-time
  writable globals with request/resource dependencies sourced from Config.
- `server/corpus_manifest.py` / `server/operator_settings.py` — ensure settings
  reads and writes use the configured settings database instead of a
  legacy-relative fallback.
- `tools/_notebook_common.py` — preserve its source/offline compatibility seam;
  production callers pass explicit bases.
- `tools/wheel_install_check.py` — redirect the child environment before first
  import, capture logs below the application root, invoke installed production
  writers, and manifest watched trees before/after launch.
- `docker/Dockerfile.server` and `infra/docker-compose.yml` — pin the existing
  writable mount to an explicit `ARXMCP_DATA_DIR` only if needed to remove
  deployment dependence on `WORKDIR`; retain current volume behavior.
- Focused tests under `tests/` — application-path aliases/escapes, configured
  route/resource/manifest consumers, always-on installed-write confinement,
  wheel packaging, and container configuration.

## Acceptance criteria

1. From roadmap AC 1: build and install the wheel into a fresh isolated venv at
   its final location; from an unrelated CWD, start its absolute
   `arxmcp-server` entry point in bootstrap mode with a temporary absolute
   application-data root, prove `server` imports from the installed wheel, and
   receive HTTP 200 from `/healthz`.
2. From roadmap AC 2: exercise real installed production writers for notebook
   state, retrieval cache, settings, a corpus marker, and harness log capture;
   enumerate the resulting delta and prove every write is beneath the selected
   root.
3. From roadmap AC 2 and 4: snapshot the repository, unrelated CWD, installed
   application/package tree, and surrounding temporary sandbox; fail on any
   unexpected mutation outside the root. Provide an always-on regression that
   detects CWD- or repository-derived writable defaults without requiring the
   full wheel build.
4. From roadmap AC 3: retain wheel behavior, Docker/Compose mounts, `make up`,
   package-relative read-only assets, and all explicit per-store overrides,
   including source-mode external-alias compatibility and installed-mode
   escape rejection.
5. From roadmap description and AC 2: pass the single configured path layout to
   notebook routes, per-notebook retrieval, MCP resources, and settings/corpus
   consumers that otherwise fall back to import-time globals.
6. From roadmap AC 5: run focused tests, the real full-wheel relocation check,
   and `make test`; Ruff and all applicable gates must pass without tool-schema
   or prompt-cache hash changes.

## External writes required

- `git push origin main`

## Open questions

1. Which smallest set of explicit path parameters removes all installed-mode
   import-time fallbacks without introducing a mutable process-global rebinding
   hook?
2. Can Docker and Compose compatibility be proven by existing mounts plus tests,
   or must both manifests add the explicit `/app/var/arxmcp` data-root setting?
3. Which production writer is the least invasive deterministic representative
   for each requested write class in the installed probe?
4. How narrowly can the portable filesystem observer state its guarantee while
   redirecting known HOME, XDG, model-cache, plotting, and temporary roots?

## Size and path decision

Expected scope is 450-700 changed lines across 8-12 files with no novel
architecture: it extends existing path and wheel-check seams. This selects the
delegated Phase 2 path. The pipeline's mid-flight file-count guard remains
binding; if a coherent implementation reaches six changed files, stop and seek
an explicit `--allow-large-diff` continuation rather than silently broadening
scope.
