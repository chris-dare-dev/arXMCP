# Implement synthesis (relocation half) — desktop-distribution-m15

Third scoped dispatch. The assembly dispatch (`f581dd0`, `907cd6c`) built the
bundle at ADR Decision 2's location, measured that `codesign` cannot seal it
there, and escalated. The owner accepted **Decision 2a** (`05dd24b`): the
payload moves to `Contents/Resources/arxmcp-desktop-child/`. This dispatch
performs the move, makes the artifact seal, and splits the supervisor's payload
resolution into an explicit two-layout disjunction.

**Base:** `05dd24b`. **Commit:** the single commit at the tip of
`worktree-agent-a6ddd29af26ebfe9a`.

## Branching note

Repo policy is main-only (CLAUDE.md §4.1), but `git checkout main` is
mechanically unavailable from this worktree — the shared checkout holds `main`.
The commit therefore landed on the worktree branch off the dispatched base
`05dd24b`, for the orchestrator to fast-forward. Nothing was pushed.

---

## What moved

- `desktop_package.place_payload` now writes to
  `Contents/Resources/<BUNDLE_NAME>/` (`desktop_package.py:1010-1030`), creating
  the parent when the shell has no `Resources` yet. Decision 1 is unchanged:
  the same bottom-up `presign_payload` signs all 180 nested Mach-O files before
  placement, and `codesign --deep` remains absent (pinned by
  `TestPreSigningIsBottomUpNotDeep`).
- The module header and `place_payload`'s docstring record why 2a is not a
  re-opening of rejected alternative R2: R2 rejected the Tauri `bundle.resources`
  CONFIG KEY (which copies without signing), not the directory.
- Nothing else about the build order changed: pre-sign → `tauri build` shell →
  place → seal.

## The dual-layout resolution

`main.rs` gained `child_payload_candidates()` + `child_payload_layout()`;
`child_payload_root()` is now a thin selector over them.

| arm | offered when | root |
|---|---|---|
| `bundle-resources` | supervisor sits in `…/Contents/MacOS` | `…/Contents/Resources/arxmcp-desktop-child/` |
| `supervisor-sibling` | always | `<supervisor dir>/arxmcp-desktop-child/` |

Design points that are load-bearing:

- The bundle candidate is offered **only** on the `Contents/MacOS` shape, so
  outside a bundle there is exactly ONE candidate. This is what makes it a
  decidable disjunction rather than a speculative `../Resources` probe.
- Selection is "first PRESENT candidate wins", where present is
  `symlink_metadata` — so a **symlinked root counts as present**, is selected,
  and is then refused by `resolve_inside()`. Skipping it would have let a
  planted symlink choose which root the supervisor launches from. m10's M13
  hardening is preserved by construction, not re-derived.
- Refusal when neither is present:
  `self-authored plan: child payload root missing (checked the bundle Resources
  and supervisor-sibling layouts)`. The wording is deliberately a SUPERSET of
  `resolve_inside`'s own "child payload root missing", because m10's runtime
  RED-state gate (`test_desktop_self_authored_launch.py:291`) matches that
  substring; that gate is byte-unchanged and passes.
- `--print-child-plan` now reports a `layout` field, so the ARM is observable
  against a real artifact instead of inferred from a path string.

### How both arms and the refusal are tested

Rust unit tests (`cargo test`, 27 passed):

- `bundle_layout_resolves_the_payload_under_contents_resources` — arm 1, and it
  asserts `resolve_inside()` still gates the selected root.
- `sibling_layout_still_resolves_outside_a_bundle` — arm 2.
- `a_non_bundle_layout_offers_only_the_sibling_candidate` — no speculative
  candidate outside a bundle.
- `neither_layout_present_is_refused` — the refusal, at both
  `child_payload_root()` and `self_authored_plan()`.
- `the_bundle_arm_wins_when_both_roots_exist` — precedence.
- `symlinked_bundle_payload_root_does_not_fall_through` — the symlinked root is
  selected and refused, never traded for a valid sibling.
- `the_probe_reports_the_selected_layout` — the wire field.
- `missing_child_payload_is_refused` (m10's) updated to the new message.

Against the REAL bundled binary (`tests/test_desktop_bundle.py`, gated):

- `TestAssembledArtifact::test_supervisor_resolves_the_child_inside_the_bundle`
  — arm 1 with `layout == "bundle-resources"`.
- `TestDualLayoutResolution::test_the_sibling_arm_still_resolves_for_the_onedir_shape`
  — the same binary copied OUT of the bundle into m7's onedir shape.
- `TestDualLayoutResolution::test_neither_layout_present_is_refused_not_guessed`
  — a shell copy with no payload anywhere.
- `TestDualLayoutResolution::test_the_bundle_arm_wins_over_a_stray_macos_payload`.
- `TestAssembledArtifact::test_a_symlinked_payload_root_is_still_refused` —
  re-pointed at the bundle `Resources` root.

`resolve_inside()` itself is BYTE-UNCHANGED. That is asserted, not asserted-by-
absence: `test_resolve_inside_is_untouched_and_still_the_gate` reads its body
for the symlinked-root refusal and checks that both callers still route the
selected root through it.

## The seal — it now succeeds

`assemble` no longer records a failure and continues; it RAISES when the seal
fails, after writing `assembly-report.json` so the evidence survives. Measured
on macOS 26.6 / Apple Silicon, `codesign` ad-hoc identity `-`:

    "seal": {"attempted": true, "sealed": true, "returncode": 0,
             "verified": true, "identity": "-"}

`codesign --verify --strict --verbose=2` over the artifact:

    .../arXMCP.app: valid on disk
    .../arXMCP.app: satisfies its Designated Requirement

Re-run independently by `test_the_seal_is_verified_against_the_artifact_not_the_report`
(against the bundle on disk, not the report). The A/B location control stays in
the build and still reports `MacOS sealed=false` / `Resources sealed=true`, with
the same `code object is not signed at all / In subcomponent: …
Contents/MacOS/payload/data.txt` output — so any future seal failure is
attributable to the layout or to the host rather than guessed at. The pinned
`sealed is False` assertion inverted to `sealed is True` plus `verified is True`
plus the "valid on disk" string.

Nothing here claims notarization. ADR Decision 3 is unchanged and
`tests/test_desktop_notarization_claims.py` is byte-unchanged and green.

## AC4, re-measured at the new location

`--print-child-plan` run out of the real assembled bundle:

| fact | value |
|---|---|
| payload location | `Contents/Resources/arxmcp-desktop-child` |
| `layout` | `bundle-resources` |
| `error` | `null` |
| `payload_root_is_symlink` | `false` |
| `child_argv0` | `…/arXMCP.app/Contents/Resources/arxmcp-desktop-child/arxmcp-desktop-child` |
| placed-vs-onedir manifest drift | 0 paths (6347 manifest entries) |
| nested Mach-O signed | 180, ad-hoc, bottom-up |
| ad-hoc signature byte-stability | stable (identical digests) |
| relocated bundle via LaunchServices | resolves inside the RELOCATED bundle, `layout=bundle-resources` |
| quarantined launch | still refused → translocation still UNVERIFIED |

The translocation record narrowed rather than closed: under Decision 2 the
bundle had no valid outer seal at all, which was reason enough for
LaunchServices to refuse; the bundle now seals and the quarantined launch is
STILL refused, so what remains is the ad-hoc identity. Re-measured, not
inherited.

## Prose corrected

- `apps/desktop/README.md` — "Child payload layout and its trust assumption"
  rewritten as the two-layout table plus the refusal and the symlink rule; the
  artifact-layout tree redrawn (payload under `Resources/`, `_CodeSignature/`
  added); the build-order sentence; "the outer bundle is not sealed" replaced
  with what the seal does and does not establish; the translocation paragraph
  re-measured; the intro's ad-hoc-signature sentence widened to cover the outer
  seal.
- `apps/desktop/crates/supervisor/src/main.rs` — `child_payload_candidates`'
  doc comment (the layout table and the 2a rationale), `child_payload_root` /
  `child_payload_layout` selection rules, `CHILD_PLAN_PROBE_ARG`'s description,
  and `resolve_inside`'s residual-risk item 1 (which said "SIBLING directory"
  as a fact).
- `pyproject.toml` — the `requires_desktop_bundle` marker description: the
  placement path, Decision 2a, the seal now being required to succeed, and the
  two-layout resolution.
- `CLAUDE.md` §4.5 — same marker's entry, including the translocation
  narrowing.
- `Makefile` — the `desktop-bundle` help line.
- `.claude/docs/adr-desktop-bundle-assembly.md` — two LIVE claims that still
  named the old location: Decision 3's "what would be submitted" spec that e4
  inherits, and the "Per-OS consequence" section, whose portable invariant
  ("the payload sits beside the supervisor") 2a falsified — restated as
  derivable-from-the-supervisor's-own-location with one enumerated candidate
  per package shape. The superseded Decision 2 text is left unedited; it is a
  record.

## Check gate results

- `make test PYTHON=…/.venv/bin/python` — **PASS, exit 0**.
  `5189 passed, 122 skipped, 1 xfailed` in 199.52s; `ruff check .` clean.
- `make desktop-bundle-check PYTHON=…` — **PASS, exit 0**. Full target: real
  `make desktop-package` onedir, `assemble`, then
  `DESKTOP_BUNDLE_GATE=1 pytest` → **62 passed, zero skips**.
- `make desktop-conformance PYTHON=…` — **exit 1 (2 from make)**, one failure:
  `tests/test_desktop_child.py::test_supervisor_owns_a_native_window_while_running`
  (`1 failed, 29 passed`). **Measured PRE-EXISTING**: the same test fails
  identically with this dispatch's `main.rs` stashed and the supervisor rebuilt
  from the base commit, so it is a property of this host's GUI/Accessibility
  session (issue #423's probe territory), not a regression from the relocation.
  Every other step of the target was run individually and passes:
  `cargo fmt --check` clean, `cargo clippy -D warnings` clean,
  `cargo test --locked --workspace` ok (27 + 8 supervisor/contract tests),
  `test_desktop_contract.py` 42 passed,
  `test_desktop_support_floor.py` + `test_desktop_self_authored_launch.py`
  57 passed. The m10 self-authored arm — the sibling layout's live gate — is
  green with its test file byte-unchanged.
- Exit codes captured with `echo $?` on their own line, never through a pipe.

## Scope report (mid-flight rule)

`git diff --stat 05dd24b..HEAD` → **8 files changed, 664 insertions(+),
222 deletions(-)**. The 350-LOC / 6-file threshold is crossed and REPORTED,
not absorbed; `allow_large_diff` was set for this dispatch. No abort: the
relocation has no partial-but-coherent stopping point — moving the payload
without the resolver's second arm produces an `.app` that cannot launch, and
moving it without inverting the seal pin produces a gate that fails on its own
green artifact. All authored; no generated artifact is in the diff.

## What could NOT be measured on this host

- **Gatekeeper path translocation** — still unverified; needs the Developer ID
  certificate e4 is blocked on. Asserted as a negative so the gap stays visible
  inside a green run.
- **Whether the artifact survives Apple's notary** — ADR Decision 3, unchanged
  and unanswerable here. A locally-valid seal is not evidence about it.
- **The native-window conformance test** — fails on this host at the base
  commit too; whether it passes in a GUI-attached session is unmeasured here.

## Deliberately not done

- Reconciling the PyInstaller executables' `minos` 11.0 against the declared
  14.0 floor (recorded, pinned, out of scope).
- Hardened runtime / entitlements.
- Widening m9's compatibility scanner or m15's notarization-claim scanner —
  both byte-unchanged.
- Any change to `resolve_inside()`.

## external_writes_required

- `git push origin main` (not performed; the implementer never pushes).
- An Apple notary submission would still be required to settle Decision 3 (e4).
