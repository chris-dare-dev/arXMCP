---
milestone_id: "desktop-distribution-m10"
research_mode: "standard"
briefs:
  - ".claude/notes/milestones/desktop-distribution-m10/research/brief-1.md"   # explore
  - ".claude/notes/milestones/desktop-distribution-m10/research/brief-2.md"   # general
external_writes_required:
  - "git push origin main"
estimated_diff_loc: 520
estimated_files: 7
implementation_path: "delegated"
---

# Research synthesis — desktop-distribution-m10

## Headline: one acceptance criterion is not achievable as written

Both researchers, working independently in separate worktrees, returned the
same load-bearing finding. `apps/desktop/crates/supervisor/tauri.conf.json`
reads `"bundle": {"active": false, ...}` with **no `resources` and no
`externalBin` key** (confirmed by direct read, 2026-08-11, and independently
by the orchestrator). m7 built the PyInstaller onedir and the
`make desktop-package` gate but never touched `tauri.conf.json`.

Consequence: **there is no `.app`, and no committed mechanism by which the
frozen Python child would live inside one.** AC1's "launching the bundled
application reaches a ready server and a rendered window" therefore has no
artifact to launch, and AC4's "resolves inside the application bundle" has no
structurally-defined bundle root to resolve against — brief-2 names this "the
single largest unknown", because the choice between `bundle.resources`,
`bundle.externalBin`, and a documented sibling-directory convention resolved
off `current_exe()` changes what AC4 even means on each OS.

This is upstream of m10's own stated scope. The e3 decomposition assumed m7
had produced a launchable artifact; m7 produced a frozen *child*, not an
application bundle. Disposition is an orchestrator/owner decision recorded
below, not an implementer decision.

## Affected files (deduped, both briefs)

| Path | Role in m10 |
|---|---|
| `apps/desktop/crates/supervisor/src/main.rs` | Core change site. `load_plan()` :70-81 (the `None` arm becomes self-authoring), `Plan` :27-63 (`#[serde(deny_unknown_fields)]`), `validate_plan()` :84-105 (pure, reused unchanged), `#[cfg(test)] mod tests` :316-403 |
| `apps/desktop/crates/supervisor/src/lifecycle.rs` | `generate_startup_token()` consumer at :110 — the self-authoring arm must reuse it, not add a second generator |
| `apps/desktop/crates/supervisor/src/redact.rs` | m6 redaction scan; needs a case exercising the self-authored path |
| `apps/desktop/crates/supervisor/tauri.conf.json` | `bundle.active: false`, no `resources`/`externalBin` — the blocker above |
| `apps/desktop/pyinstaller/desktop_package.py`, `arxmcp_desktop.spec` | m7 output shape (`BUNDLE_NAME`, `build_bundle()` :290, `COLLECT(...)` :209) — defines the onedir layout `child_argv[0]` must resolve within |
| `server/application_paths.py` | `_platform_data_root` :81-89 (the Python original), `_inside()` :59-67 (the containment pattern to mirror) |
| `tests/test_desktop_child.py` | 1611 lines; the two ONLY writers of the env var (:429, :957); AC3's "unmodified" fence |
| `Makefile` | `desktop-conformance` :161-169, `desktop-package*` :179-196 — neither exercises the unset-env path today |

## Acceptance criteria (deduped, traced to the roadmap item)

1. RED-state regression proving today's `exit(2)` at `main.rs:70-73`, not just
   the new arm's success. **Achievable.**
2. Self-authored plan fed through the SAME `validate_plan()`, refused under
   every rule. **Achievable** — see open question 4 on making it non-trivial.
3. Environment-supplied path byte-identically preserved; m5/m6/m8 gates run
   unmodified. **Achievable** — scope the diff so only `load_plan()`'s `None`
   branch changes.
4. `child_argv[0]` resolves inside the application bundle, rejected outside.
   **BLOCKED on the bundle decision** — no bundle root is structurally defined
   today.
5. Startup token fresh per launch, never persisted, absent from argv and
   diagnostics. **Achievable** — this is really about extending the m6
   redaction scan's coverage; token handling itself already satisfies it
   (generated in `lifecycle.rs`, never carried on `Plan`).
6. `make test` and `make desktop-conformance` exit 0. **Achievable**, but
   needs a genuinely new harness shape: every existing desktop-stack test
   SETS the env var; this one must remove it.
7. (Implied by the description, both briefs surfaced it) `data_root` derived
   from `_platform_data_root` — **needs a decision**: that function is Python,
   the supervisor is Rust, and no FFI bridge exists.

## Open questions (max 5)

1. **Bundle mechanism.** `bundle.resources` vs `bundle.externalBin` vs a
   sibling-directory convention off `current_exe()`. Blocks AC1 and AC4.
   Owner/orchestrator decision — see disposition below.
2. **Cross-language `_platform_data_root` parity.** Hand-port the four-branch
   logic to Rust, or have Rust ask the Python child once? Both briefs flag
   silent drift as the hazard and both recommend a regression that runs BOTH
   implementations across an env-var matrix and asserts byte-identical output
   — not a one-time eyeball.
3. **`current_exe()` is explicitly not a security primitive** (Rust stdlib
   docs). Canonicalize-then-contain closes the ordinary relocated/tampered
   sidecar case AC4 asks for; the PATH-search and hardlink attack classes the
   docs name are NOT closed by it. Record as accepted residual risk rather
   than implying the check is airtight.
4. **AC2 is trivially true as written.** A self-authored plan is never
   `smoke: true`, so the five `!smoke`-gated knobs are vacuously refused. Add
   a case proving `validate_plan`'s OTHER branch (`child_argv.is_empty()`) is
   independently reachable and refused on a self-authored plan, so both
   branches are exercised.
5. **`identity_file` vs `child_argv[0]` diverge between source and frozen.**
   Source: identity is `server/desktop_child.py` while argv invokes
   `sys.executable -m server.desktop_child`. Frozen: `identity_source_path()`
   returns `Path(sys.executable)`, so the two converge. Every existing test
   fixture has the SOURCE shape; a naive copy into the self-authoring arm
   would be wrong for the frozen case.

## Estimated size

~520 LOC across ~7 files for the self-authoring scope ALONE (self-authoring
arm ~120, containment check ~60, Rust `data_root` port ~60, parity regression
~80, Rust unit tests ~120, Python unset-env test ~100, redaction extension
~40, minus overlap). That is the **delegated** path (300–800 LOC).

Adding bundle assembly — `tauri.conf.json` wiring, embedding the ~0.75 GB
onedir, build-glue in `desktop_package.py`, and a launchable-artifact gate —
pushes the total past the 800-LOC ABORT threshold and mixes a design decision
into an implementation milestone. This is the quantitative case for the split
recommended below.

## Disposition of the blocker (orchestrator)

Recommended: **narrow m10 to the self-authoring arm, proven against m7's real
frozen onedir layout, and move the `.app` assembly into its own milestone
sequenced before m11.** m10 keeps ACs 1–3 and 5–7 with AC1's proof restated
against the built layout rather than a `.app`; AC4's containment check is
written against the onedir root, which the new milestone then re-points at the
bundle root. This keeps m10 at M, keeps the bundle-mechanism choice in a
milestone that can be critiqued on its own terms, and unblocks Phase 2 today.

Alternative: widen m10 to include bundle assembly and re-size to L, requiring
`--allow-large-diff`.

**DECIDED 2026-08-11 by the owner: split.** The roadmap was amended in the
same session — m10's ACs are narrowed and now name m7's frozen onedir layout
explicitly, and `desktop-distribution-m15` was added to own `.app` assembly
(bundle-mechanism ADR, artifact assembly, re-pointing m10's containment check
at the bundle root, and re-running m7/m8/m9's guards over the assembled
artifact). m15 is numbered last but EXECUTES second: `m10` → `m15` → `m11` →
`m12` → `m14`, with `m13` free after `m10`. `state.milestone_brief` was
re-set from the amended roadmap so the frozen brief matches the live one
(the defect m8's finding M3 recorded and deferred).

Three research findings the narrowed ACs now carry explicitly, because they
would otherwise have been discovered by the critics instead: the
`_platform_data_root` cross-language parity test, the `current_exe()`
residual-risk record, and the `child_argv.is_empty()` branch that keeps AC2
from being vacuous.

Phase 2 proceeds on the narrowed scope: delegated path, ~520 LOC, ~7 files.

## external_writes_required

- `git push origin main` — the only one. Both briefs agree: no package
  publish, no deploy, no mutating API call, no `gh` invocation anywhere in
  scope. Per-event authorization at Phase 4, main thread only.
