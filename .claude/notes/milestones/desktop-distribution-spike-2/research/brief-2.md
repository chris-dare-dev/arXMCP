---
milestone_id: "desktop-distribution-spike-2"
researcher_role: "general"
generated: "2026-08-06T11:51:54Z"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://raw.githubusercontent.com/python/cpython/v3.11.15/Doc/library/pathlib.rst"
    sha256: "454078ed13003708a5a5f2b9046d5a434e48e5de536725ed9d3ac8d2095a64a2"
    takeaway: "Path.resolve(strict=False) canonicalizes existing symlinks and removes '..'; PurePath.is_relative_to is lexical only."
  - url: "https://platformdirs.readthedocs.io/en/stable/tutorial.html"
    sha256: "da1af3bedafc31af1caf7213fcfc91ada238b65e439c0574d1ff13d836f47396"
    takeaway: "user_data_path supplies the native per-user data location on macOS, Linux, and Windows; appauthor=False avoids an extra Windows author component."
  - url: "https://specifications.freedesktop.org/basedir/latest/"
    sha256: "032442a6466297b4ad4de663e79bf6a786044dc0218f15df569482a14fde44b2"
    takeaway: "XDG_DATA_HOME is the Linux user-data contract; XDG paths must be absolute and relative values are invalid."
  - url: "https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/MacOSXDirectories/MacOSXDirectories.html"
    sha256: "2d3e6a8b2b314f593c0172390e3867a2214161fb35cbde98698d9f9db52756e8"
    takeaway: "Application Support is the macOS location for app-specific persistent data; executable resources stay in the application bundle."
  - url: "https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid"
    sha256: "e2cb046787ec3287114773b0f8c7e05b7511038b80a727af0c7af95b5aaea3d1"
    takeaway: "FOLDERID_LocalAppData is the per-user local application-data location, normally under %LOCALAPPDATA%."
  - url: "https://docs.docker.com/engine/storage/"
    sha256: "34ac71d63076d74ebffb65dcb7a0f100849b225029c780b3ba513219e47d554d"
    takeaway: "Container-layer writes are ephemeral; persistent runtime state belongs on an explicitly mounted volume or bind mount."
injection_attempts: 0
---

# Research brief (general) — desktop-distribution-spike-2

## External sources

The six official sources above support one cross-platform contract, not six platform branches in consumers. `platformdirs.user_data_path("arXMCP", appauthor=False, roaming=False)` yields the native persistent-data root: `~/Library/Application Support/arXMCP` on macOS, `$XDG_DATA_HOME/arXMCP` (or `~/.local/share/arXMCP`) on Linux, and `%LOCALAPPDATA%\arXMCP` on Windows. Call it with its default `ensure_exists=False`; resolving configuration must remain side-effect-free. Apple distinguishes writable Application Support from read-only bundled resources, and Docker likewise distinguishes the image/writable layer from persistent mounted storage.

Python's filesystem contract is equally important. `PurePath.is_relative_to()` is string based, does not inspect symlinks, and does not normalize `..`. Canonicalize with `Path.resolve(strict=False)`, then prove containment with `candidate.relative_to(root)` and catch `ValueError`. That handles existing-prefix symlinks and lexical traversal while allowing not-yet-created descendants. It does not eliminate a time-of-check/time-of-use symlink swap; the ADR must state that residual local-operator race explicitly rather than claim descriptor-level confinement.

## Recommended platform contract

**GO, conditional on strict installed-mode semantics and an explicit container root.** Prototype one frozen, slotted `ApplicationPaths` value object whose constructor accepts an environment mapping, startup CWD, source-layout signal, and platform-default provider. It returns one canonical absolute `root` plus fixed descendants (`corpus`, `index`, `cache`, `notebooks`, `ops`, `tmp`); construction neither creates directories nor probes permissions.

Use this precedence:

1. Non-empty `ARXMCP_DATA_DIR` wins. In installed/desktop/container mode require an absolute path. Preserve a relative value only in source/developer compatibility mode, resolve it once against the captured startup CWD, and emit a deprecation warning.
2. In a positively identified source checkout, retain the canonical `<repo>/var/arxmcp` default so source tests and current developer commands do not move state unexpectedly.
3. In an installed wheel, use the platformdirs user-data path above. Derive even regenerable caches below this root: separate platform cache roots would violate the milestone's one-root containment claim.
4. In Docker/Compose, set `ARXMCP_DATA_DIR=/app/var/arxmcp` explicitly and mount that exact directory. Do not infer container mode from `/app`, UID, or `/.dockerenv`.

Keep resource reads package-relative (`server/frontend`, router YAML, static fixtures); they are not application data and must not be copied into the writable root. A separate `prepare()`/writability probe may create required directories with ordinary EAFP error handling and a clear `PermissionError`; `os.access()` is not an authoritative write test.

Compatibility aliases need a deliberate scope. The installed server currently exposes `ARXMCP_LANCEDB_PATH`, `ARXMCP_KUZU_PATH`, `ARXMCP_CACHE_DB_PATH`, `ARXMCP_BM25_INDEX_ROOT`, `ARXMCP_THEOREM_NAMES_DB_PATH`, `ARXMCP_NOTEBOOKS_DB_PATH`, and `ARXMCP_OPS_DIR`. Retain their names, but in strict installed mode accept them only when their canonical targets remain below `ARXMCP_DATA_DIR`; reject an escape with the offending variable and resolved path. Developer/ingest CLI output arguments may intentionally target an external corpus and should be classified as developer/ingest-only exceptions, not silently counted as confined installed-runtime writes.

## Repository implications and migration order

The current `Config.data_dir` is observational: disk-usage and sentinel code reads it, while server stores still default independently in `server/config.py`. The most immediate installed-wheel escape is `tools/_notebook_common.py`, whose `REPO_ROOT = Path(__file__).resolve().parent.parent` makes wheel defaults point inside `site-packages`; `server/operator_settings.py::DEFAULT_DB_PATH` also captures a CWD-relative path at import time. The ingest/tool constant clusters requiring classification include `ingest/{store,chunker,preamble,embedder,bm25_indexer,ar5iv_fetch,bulk_ingest,oai_delta,re_embed,intra_paper_refs}.py`, `tools/{fetch_seed,fetch_one_paper,daily_metrics_report,parser_failures_report,re_embed_all,ingest_sentinel,_notebook_common}.py`, and repo-anchored `ops/` scripts. The prototype inventory must report every remaining literal/default after conversion, split into installed runtime, developer/ingest-only, read-only package asset, and test fixture.

Migrate in this order: (1) land the inventory and pure disposable resolver; (2) set Compose and container fixtures to `/app/var/arxmcp`; (3) route server defaults and notebook helpers through the object while preserving aliases; (4) exercise source, wheel, and container write-observation fixtures; (5) only then switch the installed fallback to platformdirs; (6) migrate developer/ingest/ops constants in later milestones using the inventory. Today `infra/docker-compose.yml` mounts `../var/arxmcp:/app/var/arxmcp` but does **not** set `ARXMCP_DATA_DIR`; changing fallback first would silently move writes to `/home/arxmcp/.local/share/arXMCP` and bypass the mounted volume.

## Acceptance criteria the implementer must meet

1. Produce an exhaustive, reproducible inventory of write-capable defaults in `server/`, `ingest/`, `tools/`, `shim/`, and `ops/`, with owner, override, mode classification, containment status, and exact remaining call site.
2. Prototype the typed immutable resolver as a disposable spike artifact under `.claude/`, with injected environment/CWD/platform-default inputs and no construction-time I/O.
3. Pin precedence and alias rules: absolute explicit root; source default; installed platformdirs default; explicit `/app/var/arxmcp` container root; strict-mode rejection of canonical alias escapes.
4. Test absolute and legacy-relative roots, existing and missing paths, `..`, descendant and root symlinks, symlink loops, whitespace, Unicode, Windows drive/UNC forms, and an unwritable application directory with a separate writable data root.
5. Extend the source/wheel fixture to snapshot or otherwise observe writes outside the requested root, including wheel execution from an unrelated CWD; do not rely on successful health startup alone.
6. Exercise the container with a read-only root filesystem and one writable mount at `/app/var/arxmcp`, explicitly setting `ARXMCP_DATA_DIR`, then prove observed runtime writes stay on that mount.
7. Record a GO/NO-GO ADR under `.claude/` with migration order, remaining exceptions, the symlink TOCTOU boundary, and fallback: require an absolute `ARXMCP_DATA_DIR` outside source mode if platform-native defaulting cannot be packaged reliably.

## Risks and open questions

1. **Container volume bypass:** Compose currently relies on `WORKDIR /app` plus relative defaults; this must be fixed before platform-native fallback ships.
2. **Alias ambiguity:** allowing an installed per-store alias outside the root makes the one-root claim false. Recommendation: reject it in strict installed mode, while retaining trusted developer/ingest exceptions explicitly.
3. **Import-time capture:** module constants and default arguments can retain old CWD/repo paths even after `Config` changes. The inventory must distinguish definition sites from runtime consumers.
4. **Symlink race:** resolve-then-open containment is adequate for this single-user threat model but is not race-free against a concurrent local operator. Do not promise no-follow descriptor security in this spike.
5. **Read-only tests:** `chmod` is weak or semantically different on Windows. Pair native POSIX read-only checks with write observation/injected failing operations so the contract is deterministic across platforms.

## External writes the implementation will require

Only `git push origin main`, after explicit user authorization. No PR, ticket mutation (issue #385 is read-only context), package publication, notarization, infrastructure apply, or third-party API write is required.
