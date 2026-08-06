# Implement synthesis — desktop-distribution-spike-1

## Built

- AC1 — built the arm64 `onedir` artifact from the local wheel and pinned offline PyInstaller inputs; all generated material stayed in `/private/tmp` (`.claude/notes/spikes/desktop-distribution-spike-1.md:13`).
- AC2 — proved relocation to a read-only Unicode/space path, unrelated CWD launch, allowlisted environment, and explicit external data root (`tools/desktop_sidecar_spike.py:18`, `.claude/notes/spikes/desktop-distribution-spike-1.md:23`).
- AC3 — reached `/healthz` and fetched `/ui/`, CSS tokens/assets, and vendored htmx from the frozen bundle (`.claude/notes/spikes/desktop-distribution-spike-1.md:25`).
- AC4 — ran FAISS/LanceDB/Kùzu/PyArrow and tiny offline safetensors Transformers operations, plus imported the real pinned loaders (`tools/desktop_sidecar_spike.py:78`).
- AC5 — recorded size, files, launches, architecture, Mach-O/RPATH closure, absolute-path scan, and ad-hoc signature checks (`.claude/notes/spikes/desktop-distribution-spike-1.md:23`).
- AC6 — recorded the host-scoped conditional GO, release NO-GO, alternatives, fallback, signing limits, and blockers in the ADR (`.claude/notes/spikes/desktop-distribution-spike-1.md:7`).
- AC7 — added regression tests and verified no model, bundle, schema, mutable bundle state, or production OpenMP workaround entered Git (`tests/test_desktop_sidecar_spike.py:14`).

## Branching note

Implementation is committed from the orchestrator-provided detached worktree because the shared main worktree was occupied; the orchestrator can fast-forward or cherry-pick the commit onto the repo's main-only history.

## Files touched

- `tools/desktop_sidecar_spike.py` — frozen runtime probe and confinement guards.
- `tests/test_desktop_sidecar_spike.py` — environment, relocation, manifest, and freeze-support tests.
- `.claude/notes/spikes/desktop-distribution-spike-1.md` — decision and measured evidence.
- `.claude/agent-memory/milestone-implementer/lessons.md` — reusable native-probe lesson.
- This synthesis — implementation handoff and gate record.

## Deferred

- Release remains NO-GO until real BGE-M3 safetensors/offline behavior and size are proved.
- Resolve and test the duplicate-OpenMP/RPATH policy without a production environment workaround.
- Developer ID signing, hardened runtime, notarization, Gatekeeper, and the macOS 14 floor remain unproved.

## external_writes_required

- git push origin main

## Test deltas

- Added 8 focused tests for sanitized launch environments, frozen-path confinement, bundle immutability detection, and `freeze_support()` ordering.

## Check gate results

- Focused: `8 passed`; targeted Ruff: clean.
- Canonical: `5006 passed, 47 skipped, 1 xfailed`; Ruff clean (approved loopback rerun after the managed sandbox denied `bind()`).
- Git status: clean after the implementation commit.
