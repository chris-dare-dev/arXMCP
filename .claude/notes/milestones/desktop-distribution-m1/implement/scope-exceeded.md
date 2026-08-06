# Scope exceeded — desktop-distribution-m1

## Guard

- Base: `feb63143b081cfbd43d5d450ce198c583db77945`.
- `ALLOW_LARGE_DIFF=false`; the Phase-2 stop threshold is 350 changed LOC.
- The coherent partial reached 373 changed LOC across five implementation
  files (270 new lines plus 80 insertions and 23 deletions). Work stopped.

## Coherent partial preserved

- `server/application_paths.py` adds the frozen typed root, fixed children,
  strict installed/container aliases, source compatibility, containment,
  platform-native fallback, and EAFP preparation contract.
- `server/config.py` exposes the resolved object and makes installed defaults
  canonical while retaining source-checkout field spellings.
- `tools/_notebook_common.py` derives mutable root aliases from the resolver.
- `server/operator_settings.py` resolves its default database at call time.
- `tests/test_application_paths.py` covers source/installed defaults, relative,
  missing, Unicode/whitespace, aliases, traversal, symlinks, and read-only EAFP.

## Remaining after rescope

- Split resolver plus focused contract tests from the three compatibility seams,
  or explicitly authorize a larger diff, before claiming the milestone complete.
- Add installed-Config and source external-alias regression assertions, plus a
  symlink-loop case, during the continuation's acceptance-criteria audit.
- Rerun the identical full gate outside the managed loopback sandbox before
  Phase 3; no production failure was observed in the sandboxed run.

## Check evidence

- Focused path/config/settings gate: PASS — 28 passed.
- Full Ruff gate: PASS.
- Full pytest: sandbox-limited — 4,979 passed, 47 skipped, 1 xfailed;
  8 failures and 6 setup errors were all `bind(127.0.0.1)` `EPERM`.

## external_writes_required

- `git push origin main` (orchestrator only; authorization-gated).
