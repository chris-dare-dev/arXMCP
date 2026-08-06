# Rectification summary — desktop-distribution-m1

## Outcome

Shipped. arXMCP now has one typed application-path resolver for source,
installed, and container modes, with CWD-independent installed defaults,
strict root containment, and compatibility seams for existing server and
notebook configuration.

## Fixed

- H1, H3 — preserved the caller-supplied field set before installed defaults
  are rebound, so notebook mode no longer mistakes derived LanceDB, cache, and
  BM25 paths for explicit conflicts; the canonical path view follows the
  effective notebook-local paths.
- H2, H4 — propagated explicit source-mode data roots and retained aliases to
  the Config fields used by runtime consumers while preserving the fully unset
  checkout-relative defaults.

## Deferred

None.

## Invalidated

None.

## Regression tests

- `tests/test_application_paths.py` — installed notebook isolation and
  source-root/external-alias propagation coverage.
- Full gate: Ruff clean; 5,002 passed, 43 skipped, 1 xfailed.

## Commits and external writes

- Implementation: `1b8385f10d052de2ce4d4df8647ac244dd75b5d8`
- Rectification: `268c219aac37304a2f2db509d42e9d27c18ce861`
- Authorized and completed: `git push origin main`
