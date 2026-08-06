# desktop-distribution-m1 — Centralize application paths

**Parent epic:** desktop-distribution-e1
**Complexity:** M

## Description

Introduce a single typed application-path resolver rooted at `ARXMCP_DATA_DIR`, with explicit paths for corpus, indices, notebooks, caches, logs, backups, and temporary state. Preserve the existing `var/arxmcp` source-checkout default while making installed-runtime behavior independent of the working directory.

## Acceptance criteria

- [ ] One module owns derivation and validation of every runtime root consumed by the server and desktop contract.
- [ ] Relative, absolute, missing, read-only, symlink, Unicode, and whitespace-containing roots have deterministic tests on supported Python platforms.
- [ ] No application path can escape the configured root through `..`, symlink traversal, or inconsistent resolution.
- [ ] Existing environment-variable values and source-checkout defaults remain backward compatible.
- [ ] `make test` exits 0.

## Verification

- [ ] Project check command passes: `make test`.
- [ ] Targeted path tests pass on macOS and the existing Windows platform lane.

## Dependencies

desktop-distribution-e1 and desktop-distribution-spike-2.

## Notes

Suggested review: `security-reviewer`, `determinism-reviewer`.

## Roadmap reference

See `plans/desktop-distribution-roadmap.md`. To execute: `milestone-pipeline desktop-distribution-m1`.
