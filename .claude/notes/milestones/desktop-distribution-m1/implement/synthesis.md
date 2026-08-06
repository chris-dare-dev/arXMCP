# Implement synthesis — desktop-distribution-m1

## Built

- AC1 — `server/application_paths.py:93` now owns one frozen, slotted path
  contract for the application root, corpus, indices, notebooks, caches, ops,
  logs, backup staging, and temporary state; `server/config.py:564`,
  `tools/_notebook_common.py:34`, and `server/operator_settings.py:106` are
  compatibility seams over that owner.
- AC2 — `tests/test_application_paths.py:15` deterministically covers relative,
  absolute, missing, Unicode/whitespace, read-only, and symlinked roots on the
  native supported platform.
- AC3 — `server/application_paths.py:116` canonicalizes every root and retained
  alias, rejects lexical traversal, descendant symlink escape, and symlink
  loops, and makes strict installed/container aliases root-confined; the
  regression matrix starts at `tests/test_application_paths.py:37`.
- AC4 — source checkout defaults remain `var/arxmcp` through
  `server/config.py:114` and sibling fields, relative source roots retain their
  captured-startup-CWD behavior with a deprecation warning, and trusted source
  aliases outside the root are explicit in `legacy_external_aliases` while
  installed aliases are strict (`tests/test_application_paths.py:56`).
- AC5 — 47 focused path/config/settings tests pass and full Ruff is clean. The
  orchestrator's authoritative unsandboxed `make test` run passed with 5,000
  tests passing, 43 skipped, and 1 expected failure.

## Branching note

Commits landed on detached HEAD because `main` is checked out in the primary
worktree. This follows the worktree constraint recorded in implementer memory;
the orchestrator can land the signed commit range onto `main`.

## Files touched

- `server/application_paths.py` — typed root selection, layout, containment,
  compatibility-alias, platform-default, and writability contract.
- `server/config.py` — resolver-backed defaults and one resolved paths object.
- `tools/_notebook_common.py` — resolver-backed notebook/corpus root aliases.
- `server/operator_settings.py` — call-time resolver-backed database default.
- `tests/test_application_paths.py` — production path-contract regression suite.
- `.claude/notes/milestones/desktop-distribution-m1/implement/scope-exceeded.md`
  — preserved Phase-2 guard checkpoint before the owner approved a large diff.
- `.claude/agent-memory/milestone-implementer/lessons.md` — append-only lessons.

## Deferred

- m2 retains broad `Resources`, route, health, wheel write-observation,
  launcher environment, offline tool, ops, and deployment-manifest migration.
- Descriptor-relative no-follow I/O against a post-resolution local symlink
  swap remains outside this cross-platform resolver contract.
- External restic repositories remain explicit operator-selected targets;
  `backups` is local staging/status and `logs` does not replace stdout logging.

## external_writes_required

- `git push origin main`

## Test deltas

- `tests/test_application_paths.py` — 7 production tests covering root modes,
  every retained alias, traversal, source compatibility, installed Config,
  symlink escape/loop behavior, and deterministic read-only failure.

## Check gate results

- Focused Ruff: PASS.
- Focused pytest: PASS — 47 passed.
- Full Ruff (`make test` first stage): PASS.
- Full pytest (orchestrator, unsandboxed): PASS — 5,000 passed, 43 skipped,
  1 xfailed.
- git status: clean after signed continuation commit.
