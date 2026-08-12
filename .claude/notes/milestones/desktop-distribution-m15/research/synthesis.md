---
milestone_id: "desktop-distribution-m15"
research_mode: "standard"
briefs:
  - ".claude/notes/milestones/desktop-distribution-m15/research/brief-1.md"   # explore
  - ".claude/notes/milestones/desktop-distribution-m15/research/brief-2.md"   # general
external_writes_required:
  - "git push origin main"
estimated_diff_loc: 900
estimated_files: 10
implementation_path: "delegated"
---

# Research synthesis — desktop-distribution-m15

## Headline: the ADR's three named options are a false choice

m15's first acceptance criterion says the bundle mechanism is chosen in an ADR
"naming the rejected alternatives" among `bundle.resources`,
`bundle.externalBin`, and a sibling-directory convention. The general
researcher's sourced finding is that **two of the three are broken or
unconfirmed for this payload**, and the third is not a Tauri mechanism at all:

- **`externalBin` does not fit the shape.** It expects one executable file per
  platform (`name-$TARGET_TRIPLE`), not a directory. m7's payload is a
  PyInstaller **onedir** — hundreds of `.so`/`.dylib` files plus an
  executable. Independently, Tauri issue #11992 (open, untriaged, v2) reports
  notarization rejecting the **main app binary** with an invalid-signature
  error *specifically when `externalBin` sidecars are present*; removing
  `externalBin` fixes it.
- **`bundle.resources` embeds directories fine but does not sign them.**
  Discussion #12001 is community-confirmed: dylibs shipped via `resources`
  are not signed by the Tauri build and fail notarization, while dylibs
  shipped through the macOS `frameworks` mechanism are signed and do
  notarize. There is no first-class "sign my resources tree" feature.
- **The sibling-directory convention is what m10 already built and hardened**
  — but it is not a Tauri config key. Placing the onedir inside
  `Contents/MacOS/` requires custom build glue and custom pre-signing before
  Tauri's bundler runs.

Corroborating precedent: PyInstaller issue #8927 — a `--onedir` app notarizes
fine as `--onefile` but **fails notarization as onedir even when local
`codesign --deep --strict` reports valid**. Apple's notary service is stricter
than local verification for multi-file trees.

**The likely real answer is a hybrid**: Tauri builds the `.app` shell
(window + supervisor binary, `bundle.active: true`, no `resources`, no
`externalBin`), and a post-build step owned by `desktop_package.py` — m7's
existing owner of the onedir — copies the pre-signed payload into
`Contents/MacOS/` and re-seals the outer bundle. The ADR should say that
plainly rather than force-fit the roadmap's three options.

## The blocker under the blocker

**The notarization question cannot be settled by research, and cannot be
settled by m15 either.** Resolving whether any of these layouts survives
Apple's notary service requires a build-and-submit trial, which requires the
Developer ID certificate that `desktop-distribution-spike-4` has never been
able to run and that e4 is blocked on. No further web research will close it.

This does not block m15 from producing a launchable `.app` — double-click,
ready server, rendered window are all provable today. It blocks m15 from
claiming the layout is **notarization-ready**. Those must be separated in the
acceptance criteria, or m15 will ship a claim it has not earned — the same
discipline m9 applied when it declared the macOS 14 floor DECLARED-but-
UNVERIFIED rather than pretending hardware it does not have.

## Affected files (deduped)

| Path | Role |
|---|---|
| `apps/desktop/crates/supervisor/tauri.conf.json` | `bundle.active` false -> true; the mechanism keys the ADR selects |
| `apps/desktop/pyinstaller/desktop_package.py` | m7's onedir owner; the natural home for assembly + pre-signing glue |
| `apps/desktop/crates/supervisor/src/main.rs` | `child_payload_root()` re-points at the bundle root. `resolve_inside()` is generic and does NOT change — m10's claim verified |
| `Makefile` | a new target that builds BOTH the Rust binaries and the bundle in one session |
| `tests/test_desktop_package.py`, `tests/test_desktop_support_floor.py` | m7/m9 guards to re-run over the assembled artifact |
| `tests/test_desktop_self_authored_launch.py` | m10's AC1 fixture proof, upgraded to the real artifact |
| `apps/desktop/README.md` | AC7's layout record, which e4 consumes |
| new ADR under `.claude/docs/` | AC1's deliverable |

## Open questions (max 5)

1. **Does m15 claim notarization-readiness?** It cannot prove it. Recommend
   splitting the AC: prove assembly + launch + guard re-runs now; record the
   notarization question as OPEN with the named evidence, for e4 to close.
2. **Hybrid vs stock Tauri config.** The evidence points at the hybrid. It
   costs a bespoke assembly script the ADR must own, and buys the only path
   with no unresolved-mechanism risk.
3. **No gate builds the Rust supervisor and the ~0.75 GB bundle together.**
   Unchanged since m10 — this is new gate authoring, not a re-point, and it
   is what forced m10's AC1 onto a fixture. Likely a new opt-in marker
   following the `requires_desktop_package` / `requires_bundled_model`
   precedent.
4. **The PyInstaller executables' own `minos` is unpinned and unchecked
   anywhere in the repo.** The Rust side is pinned by `.cargo/config.toml`;
   there is no equivalent for the CPython/PyInstaller build, so m9's floor
   claim currently rests on the Rust half plus a wheel-tag inference. Needs
   `otool -l` against a real build. **This is arguably m9's gap, surfaced by
   m15** — decide whether m15 closes it or files it.
5. **First-ever use of Tauri's bundler here.** No `tauri-cli` in `Cargo.lock`,
   no `.app`/`.dmg` output anywhere. New build-time dependency and possibly a
   new hash-pin surface; the ADR should name the toolchain onboarding.

## Estimated size

~900 LOC across ~10 files: assembly + pre-signing glue in `desktop_package.py`
(~250), the new combined gate (~150), re-pointed guards and their tests
(~250), `child_payload_root` and its tests (~80), ADR + README (~170).
Delegated path. `allow_large_diff` was set at init.

Calibration: m10 measured ~1,227 LOC against a ~520 estimate. This estimate is
deliberately not optimistic, and m15 additionally onboards a new toolchain.

## external_writes_required

- `git push origin main` — the only one. Both briefs agree. Note the ADR's
  central question would require an Apple notary submission to settle
  empirically; that is NOT in scope here and would be an external write
  belonging to e4/spike-4.
