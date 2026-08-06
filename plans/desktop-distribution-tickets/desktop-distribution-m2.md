# desktop-distribution-m2 — Make the installed server relocatable

**Parent epic:** desktop-distribution-e1
**Complexity:** M

## Description

Route the server, notebook registry, retrieval stores, and operational outputs through the centralized path contract for installed-runtime flows. Add a wheel relocation smoke that starts in bootstrap mode from an arbitrary working directory and proves no write lands beside the application or checkout.

## Acceptance criteria

- [ ] The installed `arxmcp-server` starts with a temporary application-data root from outside the repository and reaches `/healthz` in bootstrap mode.
- [ ] Notebook, cache, log, corpus-marker, and settings writes observed in the smoke remain beneath that root.
- [ ] The wheel, Docker/Compose, `make up`, and existing explicit per-store overrides retain their current behavior.
- [ ] A regression test fails if an installed-runtime code path derives a writable location from `cwd` or repository root.
- [ ] `make test` exits 0.

## Verification

- [ ] Project check command passes: `make test`.
- [ ] Build and inspect the wheel, then execute the relocation smoke from a temporary directory.

## Dependencies

desktop-distribution-e1, desktop-distribution-m1, and desktop-distribution-spike-1.

## Notes

Suggested review: `security-reviewer`, `determinism-reviewer`.

## Roadmap reference

See `plans/desktop-distribution-roadmap.md`. To execute: `milestone-pipeline desktop-distribution-m2`.
