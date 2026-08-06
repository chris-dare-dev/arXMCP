# Research synthesis — desktop-distribution-spike-2

## Readiness and provisional decision

**Proceed: conditional GO.** Both research passes agree that arXMCP's
first-party installed-runtime writes can be routed beneath one explicit data
root. The proof must include launcher-owned redirection for library state
(Hugging Face/XDG caches, multipart/temp files, Matplotlib, and MinerU HOME)
and must reject out-of-root per-store aliases in strict installed mode.

The spike remains inventory and prototype only. It must not wire the resolver
through production consumers or silently change source, wheel, Compose, or
operator behavior; those migrations begin in `desktop-distribution-m1`/m2.

## Affected files (deduplicated)

- `tests/test_desktop_data_root_spike.py` — disposable, executable frozen
  `ApplicationPaths` prototype plus source/wheel/container fixture proofs and
  path-containment edge cases.
- `.claude/notes/spikes/desktop-distribution-spike-2.md` — authoritative write
  inventory, compatibility aliases, exact remaining call-site groups,
  migration sequence, evidence, and GO/NO-GO ADR with fallback.
- Existing files are evidence inputs only in this spike: `server/config.py`,
  `tools/_notebook_common.py`, `server/operator_settings.py`, installed server
  writers/routes/trackers, `ingest/`, `tools/`, `shim/`, `ops/`, `Makefile`,
  `tools/wheel_install_check.py`, `docker/Dockerfile.server`,
  `infra/docker-compose.yml`, K8s manifests, and test fixtures.

No production path consumer, dependency lock, MCP schema, prompt hash, or
container manifest should change during the spike.

## Acceptance criteria (spike brief traced)

1. **AC1 — inventory:** record a reproducible inventory across `server/`,
   `ingest/`, `tools/`, `shim/`, and `ops/`, classifying each write/default as
   installed daemon/spawned work, developer/ingest-only output, read-only
   package input, test fixture, or intentional external operator target.
2. **AC2 — prototype:** exercise one immutable typed resolver rooted at
   `ARXMCP_DATA_DIR` against source-checkout, installed-wheel, and
   Docker/Compose fixture semantics without production wiring.
3. **AC3 — containment:** prove absolute, relative, missing, read-only,
   symlink, traversal, whitespace, Unicode, Windows drive/UNC, and
   read-only-application/writable-data-root behavior deterministically.
4. **AC4 — compatibility and migration:** record retained aliases, strict
   installed-mode precedence, source compatibility, exact remaining
   call-site groups, and migration order. Explicitly reject the fiction that
   arbitrary out-of-root aliases remain compatible with a one-root contract.
5. **AC5 — decision:** publish a GO/NO-GO ADR with evidence, residual symlink
   TOCTOU boundary, container-volume ordering, and the isolated
   HOME/XDG/temp plus deny-write-sandbox fallback.

## Prototype contract to prove

1. Explicit non-empty `ARXMCP_DATA_DIR` wins. Installed/desktop/container
   mode requires it to be absolute; source compatibility may resolve a
   relative value once against captured startup CWD with deprecation.
2. Positively identified source checkout with no override keeps canonical
   `<repo>/var/arxmcp`, independent of later CWD changes.
3. Installed wheel with no override uses an injected platform-native default
   provider (the ADR recommends `platformdirs.user_data_path`); the spike
   prototype takes this provider as an input and adds no dependency.
4. Container mode is explicit: `ARXMCP_DATA_DIR=/app/var/arxmcp` and one
   matching writable mount. Never infer container mode from `/app`, UID, or
   `/.dockerenv`.
5. Fixed children cover corpus, indices (`lancedb`, `kuzu`, BM25, SQLite),
   notebooks, cache, ops, logs, backups, and temp. Construction is pure;
   writability preparation is separate and EAFP-based, never `os.access()`.
6. Canonicalize with `resolve(strict=False)` and prove descendants with
   `relative_to`; construction-time validation does not claim race-free
   descriptor/no-follow I/O at later write sites.

## Inventory conclusions carried into the ADR

- Immediate installed escapes include package/CWD-relative defaults in
  `tools/_notebook_common.py`, `server/operator_settings.py`, and independent
  fields in `server/config.py`.
- Installed work includes SQLite stores/migrations, BM25 auto-builds,
  notebook upload/ingest/render state, spawned ingest, model caches, and temp
  spooling—not merely paths named in `Config`.
- `infra/docker-compose.yml` mounts `/app/var/arxmcp` but does not explicitly
  set `ARXMCP_DATA_DIR`; changing installed fallback first would bypass the
  mounted volume.
- Package assets, external restic repositories/restore destinations, Lean
  binaries, CA bundles, and explicit developer/ingest output arguments are
  not application-data children.
- Migration order: resolver contract → container env/mount contract → Config
  and notebook aliases → installed server writers/spawned ingest → launcher
  cache/temp redirects → wheel/container observation → offline ingest/tools
  → ops/Makefile.

## External writes required (verbatim from brief-2)

```yaml
external_writes_required:
  - "git push origin main"
```

The start annotation already posted to issue #385 is pipeline metadata. No
push, issue closure, package publish, deploy, or infrastructure mutation is
authorized by this phase.

## Risks and open questions (max 5)

1. Container proof should treat current Compose as evidence of the missing
   explicit env contract; the spike must not fix the manifest prematurely.
2. Native POSIX chmod evidence is not portable to Windows; pair it with an
   injected failing operation and write-observation fixture.
3. Keep the executable prototype disposable and unimported by production;
   m1 must re-author the production module from the accepted ADR contract.
4. Snapshot package/CWD and requested data root around wheel/source fixtures
   so a successful health response cannot mask an out-of-root write.
5. If a native dependency still escapes redirected HOME/XDG/temp, the ADR
   fallback is an isolated launcher environment plus deny-write sandbox—not a
   weakened one-root claim.

## Scope estimate and Phase 2 routing

Estimate **400–650 LOC across 2 files**. Although the file count is small,
the cross-platform path/security prototype is a novel contract and the
inventory is broad, so Phase 2 routes to the pipeline's **delegated**
implementation path. The 800-LOC hard guard still applies; if exceeded,
reduce evidence prose or split machine-readable inventory rather than wiring
production consumers into the spike.
