# Scope exceeded — desktop-distribution-m2

## Guard

- `ALLOW_LARGE_DIFF`: `false`
- Implementation base: `092ab7b5f6e6d30dd2b6358074d0a7b97b12d57d`
- Coherent implementation slice: 5 source/test files, 292 changed lines
- Next required acceptance-criterion file: `tools/wheel_install_check.py`
- Trigger: that edit would be file 6, meeting the `>=6` hard stop

## Partial implementation committed

- HTTP notebook writers resolve notebook paths from
  `request.app.state.config.application_paths`.
- UI preview reads resolve notebook and corpus roots from the same Config.
- Per-notebook retrieval opens and freshness probes pass the configured
  notebooks base explicitly.
- MCP notebook and corpus-manifest resources use the live Config paths,
  including the configured operator-settings database.
- Always-on regressions poison import-time defaults and prove the Config-owned
  paths win for each consumer family.

## Deferred acceptance criteria

- Extend the installed-wheel smoke to redirect HOME/XDG/model/temp roots,
  capture stdout beneath `ApplicationPaths.logs`, invoke production cache,
  settings, notebook, and corpus-marker writers, and compare manifests.
- Prove `/healthz` plus the observed writer set from an unrelated CWD against
  the freshly installed wheel.
- Add explicit container data-root environment wiring only if the existing
  Docker/Compose mount-contract tests prove it is needed.
- Re-run the full wheel relocation gate after those changes.

## Verification

- Focused consumer regressions: PASS (`3 passed`).
- Existing route/resource/retrieval regressions: PASS (`231 passed`).
- Canonical `make test`: PASS (`5011 passed, 47 skipped, 1 xfailed`).
- Ruff: PASS.

## External writes

- `git push origin main` remains Phase 4 only; no external write was made.
