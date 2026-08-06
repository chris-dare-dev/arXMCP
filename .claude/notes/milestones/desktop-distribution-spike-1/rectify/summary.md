# Rectification summary — desktop-distribution-spike-1

## Outcome

Conditional GO. A disposable PyInstaller 6.21 `onedir` sidecar relocated to a
read-only Unicode path, served the operator UI without ambient Python, and
completed the combined native/tiny-model probe. Production release remains
blocked by the real-model, support-floor, native-library, and signing gates in
the ADR.

## Fixed

- H1, H2 — replaced symlink-following artifact totals with 5,530 regular files,
  19 symlinks, 759,839,270 logical bytes, and 772,259,840 allocated bytes; the
  native census now distinguishes 180 regular Mach-O files from 19 aliases.
- M1, M3 — made bundle manifests stream regular-file contents and hash symlink
  targets, with equal-size mutation and same-length retarget coverage.
- M2 — disclosed the inert `direct_url.json` build URI and made sanitization
  plus full regular-file build-root scanning an explicit release blocker.

## Deferred

None.

## Invalidated

None.

## Regression tests

- `tests/test_desktop_sidecar_spike.py` — 10 focused tests passed.
- Frozen content-aware rerun: combined native/model probe passed and the bundle
  hash remained `00d985fa…e9cee1` before and after.
- Full gate: Ruff clean; 5,012 passed, 43 skipped, 1 xfailed.

## Commits and external writes

- Research checkpoint: `10b8641a509b140ab5dcfd3e132e9578a169531a`
- Implementation: `ddd1d508bf8d01cf099a4ef2750e17bc824fdc3e`
- Rectification: `0180e72e65f97c9f862310aefac1bc915e78851d`
- Authorized and completed: `git push origin main`
