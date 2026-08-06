# Implement synthesis — desktop-distribution-spike-2

## Built
- AC1: inventoried installed, spawned, offline, shim, ops, input, and external destinations at `.claude/notes/spikes/desktop-distribution-spike-2.md:33`.
- AC2: proved one frozen typed resolver across source, wheel, and container fixtures at `tests/test_desktop_data_root_spike.py:48`.
- AC3: covered absolute/relative, missing, space/Unicode, symlink, traversal, and read-only-app containment at `tests/test_desktop_data_root_spike.py:130`.
- AC4: pinned aliases, precedence, remaining owners, and migration order at `.claude/notes/spikes/desktop-distribution-spike-2.md:53`.
- AC5: accepted a conditional GO with TOCTOU boundary and fallback at `.claude/notes/spikes/desktop-distribution-spike-2.md:70`.

## Branching note
Committed on detached HEAD for orchestrator landing on `main`, per the dispatch adaptation to `CLAUDE.md` §4.1's main-only policy.

## Files touched
- `tests/test_desktop_data_root_spike.py` — disposable resolver and fixtures.
- `.claude/notes/spikes/desktop-distribution-spike-2.md` — inventory and ADR.
- This synthesis and the mandatory implementer-memory append.

## Deferred
- All production consumers, manifests, platformdirs dependency, and migrations.

## external_writes_required
- `git push origin main` (orchestrator only, after explicit authorization).

## Test deltas
- Six focused tests added; no production test or schema pin changed.

## Check gate results
- Focused pytest: PASS (6 passed); focused ruff: PASS.
- `make test PYTHON=/Users/chris.dare/Personal/SourceCode/arXMCP/.venv/bin/python`: PASS (4985 passed, 47 skipped, 1 xfailed; ruff clean).
- git status after final commit: clean.
