# Rectification summary — desktop-distribution-spike-2

## Outcome

Conditional GO. The disposable prototype now proves one canonical application-
data root across source, installed-wheel, and container fixtures without wiring
the resolver into production consumers.

## Fixed

- H1, H4 — expanded and regression-pinned the installed control-loop,
  spawned-fetch, ops, build-only, and no-write scaffold classifications.
- H2 — redirected Windows profile/AppData variables below the root and proved
  the redirects survive the MinerU environment scrubber.
- H3, M1 — replaced the predictable destructive probe with an exclusive,
  randomized temporary file and preserved pre-existing files and symlinks.
- M2 — validated retained installed/container aliases during root resolution.
- M3 — added a platform-neutral observer that rejects writes beside an
  installed application or in its startup CWD.
- M4 — modeled the container mount contract and rejected missing, read-only,
  relative, mismatched, and duplicate mounts.

## Deferred

None.

## Invalidated

None.

## Regression tests

- `tests/test_desktop_data_root_spike.py` — 10 focused tests passed.
- Full gate: Ruff clean; 4,993 passed, 43 skipped, 1 xfailed.

## Commits and external writes

- Implementation: `fd5e625bd668731d38ff29e46d0870270b24f116`
- Rectification: `2b46547e96faaa84d33d47ea105d818ef7ee034b`
- Authorized and completed: `git push origin main`
