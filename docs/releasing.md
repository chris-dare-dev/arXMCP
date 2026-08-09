# Releasing

Maintainer workflow for cutting a versioned arXMCP release. arXMCP follows
[Semantic Versioning](https://semver.org/) and is currently in the `0.x`
pre-release line (the public API may change between minors until `1.0.0`).

## What a version means here

- **MAJOR** (`1.0.0`) — reserved for the production cutover (E11) and a
  stabilized MCP tool surface.
- **MINOR** (`0.N.0`) — new capabilities (tools, indices, ingest paths).
- **PATCH** (`0.N.M`) — fixes and doc/security patches with no surface change.

The MCP tool surface is the contract that matters most: any change to
`tools/list` (a new tool, a renamed argument, a schema bump) is at least a
MINOR and must re-pin `EXPECTED_TOOL_SCHEMA_SHA256`.

## Release checklist

1. **Green build.** `make test` passes (ruff + pytest) and `make sbom`
   reports no critical CVEs.
2. **Clean-environment install.** `make wheel-check-full` exits 0.

   This is a separate gate from `make test` on purpose. A packaging bug is
   invisible to the test suite: the repo root is on `sys.path` and every
   data file is right there on disk, so the suite passes, the server runs,
   and `make up` works — while the built wheel ships none of it. Before
   2026-07-31 the wheel was missing the entire `ops/` layer (backup,
   cutover, restore drill, drift watchdog), the console assets,
   `server/router_patterns.yaml`, `server/schemas/*.json` and
   `tools/seed-papers.txt`, and declared no `arxmcp-server` console script
   at all. Nothing in the suite noticed, and an operator would have hit a
   `RuntimeError` on the missing router patterns before serving one
   request.

   `make wheel-check-full` builds the wheel, installs it into an isolated
   venv that resolves the real dependency set, boots it with
   `ARXMCP_BOOTSTRAP_MODE=1` and polls `/healthz`. Budget ~4 min on a warm
   `uv` cache, ~15 min cold. `make wheel-check` is the ~10 s subset (file
   inventory + console scripts, no dependency resolve) for quick loops.
3. **Desktop bundle (if the release ships one).** `make desktop-package`
   builds the PyInstaller `onedir` sidecar into `var/desktop-package/dist/`
   from the committed spec (`apps/desktop/pyinstaller/arxmcp_desktop.spec`)
   and fails on any build-machine path string in the artifact.
   `make desktop-package-check` is the full gate: two consecutive builds
   proving a byte-identical manifest (closed, size-pinned exception set),
   frozen `latex2mathml` byte-parity, the `freeze_support()` spawn guard,
   and `direct_url.json` sanitization — budget ~150 s of builds after the
   one-time build-venv provisioning. Each build runs against its own cold
   `PYINSTALLER_CONFIG_DIR`, so the determinism claim covers the native
   binaries rather than replaying the first build's bincache.

   **Prerequisites and footprint.** macOS/Linux only —
   `requirements-build.txt` is a macOS-resolved hash-pinned lock with no
   environment markers, and `--require-hashes` forbids resolving the
   Windows dependency it omits. The first run **requires network** to
   provision the build venv. `var/desktop-package/` is **persistent**: ~1 GB
   of deliberately-reused build venv plus ~0.75 GB per bundle (~2.5 GB at
   the two-build peak). Reclaim it with `make desktop-package-clean`.

   **Supervisor wiring.** The frozen child derives its identity digest from
   its OWN executable bytes (`server/desktop_child.py::identity_source_path`),
   matching what the supervisor hashes — so the supervisor plan's
   `identity_file` must point at the frozen executable in the bundle, not at
   `server/desktop_child.py`. Pointing it at the source module makes every
   launch fail the identity check.

   PyInstaller is deliberately NOT in `pyproject.toml`/`uv.lock` (the MinerU
   precedent): the driver provisions `var/desktop-package/build-venv` from
   `uv.lock`'s runtime set plus the hash-pinned build stack in
   `apps/desktop/pyinstaller/requirements-build.txt`. To bump PyInstaller,
   edit `requirements-build.in`, regenerate the hashed lockfile per its
   header comment, and re-run `make desktop-package-check`.
4. **Pick the version** per the rules above.
5. **Update [`CHANGES.md`](../CHANGES.md).** Move the relevant `Unreleased`
   entries into a new `## [x.y.z] — YYYY-MM-DD` section and add a compare
   link at the bottom.
6. **Update `version`** in [`pyproject.toml`](../pyproject.toml).
7. **Commit** the bump: `chore(repo): release vX.Y.Z`.
8. **Tag** an annotated, GPG-signed tag (signing is enabled repo-wide):

   ```sh
   git tag -s vX.Y.Z -m "arXMCP vX.Y.Z"
   ```

9. **Push** the commit and tag (push is per-event authorized):

   ```sh
   git push origin main --follow-tags
   ```

10. **Cut the GitHub Release** from the tag. The repo's
   [`.github/release.yml`](../.github/release.yml) categorizes
   auto-generated notes by conventional-commit prefix; paste the
   `CHANGES.md` section in as the human summary above the generated list.
11. **Attach assets** if any (the GitHub release-downloads badge counts
   these).

## Conventions

- Tags are `vMAJOR.MINOR.PATCH` (leading `v`).
- Never force-push tags or `main`.
- Never `--no-gpg-sign` / `--no-verify`.
- The changelog is `CHANGES.md` (epic-grain history + a release section);
  there is no separate `CHANGELOG.md` by project decision.

## First release

`v0.1.0` marks the current pre-release substrate (E01–E14 shipped, with E12
folded into E11: ingest, retrieval, the eight-tool MCP surface, citation
graph, notebook workflow, observability). It is prepared but **not yet
tagged** — the maintainer cuts it when ready, following the checklist above.
