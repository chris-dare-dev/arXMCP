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
2. **Pick the version** per the rules above.
3. **Update [`CHANGES.md`](../CHANGES.md).** Move the relevant `Unreleased`
   entries into a new `## [x.y.z] — YYYY-MM-DD` section and add a compare
   link at the bottom.
4. **Update `version`** in [`pyproject.toml`](../pyproject.toml).
5. **Commit** the bump: `chore(repo): release vX.Y.Z`.
6. **Tag** an annotated, GPG-signed tag (signing is enabled repo-wide):

   ```sh
   git tag -s vX.Y.Z -m "arXMCP vX.Y.Z"
   ```

7. **Push** the commit and tag (push is per-event authorized):

   ```sh
   git push origin main --follow-tags
   ```

8. **Cut the GitHub Release** from the tag. The repo's
   [`.github/release.yml`](../.github/release.yml) categorizes
   auto-generated notes by conventional-commit prefix; paste the
   `CHANGES.md` section in as the human summary above the generated list.
9. **Attach assets** if any (the GitHub release-downloads badge counts
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
