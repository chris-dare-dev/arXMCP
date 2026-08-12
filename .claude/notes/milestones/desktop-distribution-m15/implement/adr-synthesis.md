# Implement synthesis (ADR half) — desktop-distribution-m15

Scoped dispatch: AC1 + AC2 only. No `tauri.conf.json` change, no assembly or
pre-signing glue, no `child_payload_root()` edit, no Makefile target, no test.
The assembly implementation is a separate dispatch after owner review.

## Built

- **AC1** — `.claude/docs/adr-desktop-bundle-assembly.md` (new, Proposed).
  Decision 1 chooses the hybrid (Tauri shell + `desktop_package.py`-owned
  pre-signing and post-build placement + outer re-seal) as first-class, not as a
  fallback. Decision 2 fixes the payload at `Contents/MacOS/arxmcp-desktop-child/`.
  Five rejected alternatives are named with their evidence (§ "Rejected
  alternatives" R1–R5). Per-OS consequence stated in its own section.
- **AC2** — Decision 3 records the notarization question as OPEN, states that
  nothing in this repo can settle it, names the build-and-submit trial under the
  Developer ID certificate `desktop-distribution-spike-4` has never been able to
  run as the only closure, and specifies what would be submitted (assembled
  `arXMCP.app` + a fixture-sized control so a rejection is attributable to
  mechanism rather than scale). A binding language rule forbids any
  notarization-ready / Gatekeeper-ready / signable-as-is claim in any artifact
  this milestone touches, and separates the four distinct questions (assembles /
  launches / signed at all / notary accepts) per §4.9.
- Cross-reference: `apps/desktop/README.md` gains a pointer to the ADR in the
  intro block and a correction in "Child payload layout" noting the ADR proposes
  keeping the sibling relation inside the bundle rather than replacing it, with
  an explicit "this is a decision record, not a description of a built artifact"
  hedge.

## The decision, in one paragraph

Neither stock Tauri key works for a ~0.75 GB multi-file PyInstaller onedir:
`externalBin` takes one executable per target triple and carries an open,
untriaged v2 bug where its mere presence fails notarization of the MAIN app
binary (issue #11992); `bundle.resources` embeds directories fine but does not
sign their contents, which then fail notarization (discussion #12001,
community-confirmed only), and PyInstaller issue #8927 shows that exact failure
class at onedir scale even when local `codesign --deep --strict` passes. The
`frameworks` mechanism is the one path confirmed to be signed at build time, but
is specified for frameworks and named dylibs, not a Python closure — recorded as
the fallback if a notary trial rejects the hybrid. The hybrid is chosen because
it is the only path with no unresolved *mechanism* risk; its cost is
implementation effort, which is recoverable.

## Evidence handling

Every external source is tabulated with URL, sha256 and a **status** column that
keeps community-claimed claims community-claimed (E4, E6) and vendor-documented
ones separate (E1, E2, E5). Three things are recorded as explicitly NOT
established: where `externalBin` sidecars land in `Contents/`, whether
pre-signing + `resources` passes the notary, and whether any layout in the ADR
passes the notary.

## Left undecided, deliberately

Eight items, enumerated in the ADR's "What this ADR deliberately does NOT decide":
assembly hook vs post-build step; what signing identity is used with no
certificate; distribution container (zip vs DMG); assembled-level determinism;
the PyInstaller executables' own `minos` (roadmap AC10); the combined gate's
name/marker/target; the notarization-claim regression's scan scope; and
`apps/desktop/README.md`'s artifact-layout section (AC7), which must be written
from the measured artifact.

## What the assembly dispatch now needs to do

1. Flip `bundle.active` to `true`, add no `resources`/`externalBin`/`frameworks`.
2. Add bottom-up pre-signing of every nested Mach-O in the onedir to
   `desktop_package.py` — not `codesign --deep`, which is the shortcut E6's
   precedent defeated — plus placement into `Contents/MacOS/arxmcp-desktop-child/`
   and an outer re-seal.
3. Onboard and **pin** `tauri-cli` (first bundler use in this codebase; no
   `tauri-cli` in `Cargo.lock`). Unpinned is ruled out by the ADR; the mechanism
   is not.
4. Prove AC4 against the real bundle rather than inheriting it. Decision 2 leaves
   `child_payload_root()`'s body already correct, but two things stay unverified:
   `current_exe()` under Gatekeeper path translocation, and whether assembly or
   re-seal introduces a symlink at the payload root (which `resolve_inside()`
   refuses).
5. Author the combined Rust + PyInstaller gate (none exists; unchanged since
   m10's rectify) with its own opt-in marker.
6. Correct the two now-stale prose sites that predict the convention is replaced:
   `apps/desktop/crates/supervisor/src/main.rs:307-310` and the README section.
7. Build the AC2 notarization-claim regression, deciding its own scan scope —
   m9's guard covers root `*.md`, `docs/**`, `apps/**.md` and the Rust crates, and
   does NOT cover `.claude/docs/`.

## Files touched

- `.claude/docs/adr-desktop-bundle-assembly.md` — new ADR (AC1 + AC2).
- `apps/desktop/README.md` — two cross-reference edits, no layout claim added.
- `.claude/notes/milestones/desktop-distribution-m15/implement/adr-synthesis.md` — this file.

## Branching note

Repo policy is main-only (CLAUDE.md §4.1). `git checkout main` is mechanically
unavailable from this worktree because the shared checkout holds `main`, so the
commit landed on `worktree-agent-ac8bdf7f4ab073e6f`, off the dispatched base
`525de97c01bb484522571523d346c2788c147bfc`. The orchestrator fast-forwards.

## external_writes_required

- `git push origin main` (from the research briefs; unchanged — not performed here)
- An Apple notary submission would be required to settle Decision 3. Out of scope
  for m15; belongs to e4 / `desktop-distribution-spike-4`.

## Test deltas

None. Docs-only diff by dispatch scope.

## Check gate results

- `pytest tests/test_desktop_support_floor.py`: PASS (exit 0, 31 passed 2 skipped) —
  the m9 compatibility-claim scanner covers `apps/**.md`, so the README edit is
  gated by it.
- `pytest tests/test_runbook_index.py tests/test_constitution_ui_claims.py`: PASS
  (exit 0, 46 passed) — the other two markdown-scanning guards.
- `ruff check .`: SKIP — no `.py` file touched.
- `make test` / `make desktop-conformance`: SKIP — no code, config or test file
  in the diff. The assembly dispatch owns both.
- `git status --porcelain`: clean after commit.
