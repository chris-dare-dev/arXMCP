---
milestone_id: "desktop-distribution-m11"
research_mode: "standard"
briefs:
  - ".claude/notes/milestones/desktop-distribution-m11/research/brief-1.md"   # explore
  - ".claude/notes/milestones/desktop-distribution-m11/research/brief-2.md"   # general
external_writes_required:
  - "git push origin main"
estimated_diff_loc: 1200
estimated_files: 14
implementation_path: "delegated"
---

# Research synthesis — desktop-distribution-m11

## The brief's stated mechanism does not exist, and that is the orchestrator's error

m11's brief says the selection "persists through `OperatorSettingsStore`
(`server/operator_settings.py`) … so no new store is introduced." Both
researchers independently established that this is impossible:
`OperatorSettingsStore`'s database is `var/arxmcp/cache/notebooks.db` —
**inside the data root**. A store that lives in the root cannot record where
the root is.

That sentence was written in the e3 decomposition without checking the store's
location. It is the brief's error, not a constraint to force-fit.

## What m11 actually has to build

Four things, none of which exist today:

1. **A root-pointer artifact that is NOT data-root-relative**, read by BOTH
   languages before either resolves anything: Python's
   `ApplicationPaths.resolve` and Rust's `self_authored_plan`. m10 pinned
   those two implementations together with an executable parity matrix; an
   override read inserted ahead of them changes the resolution order both
   parity tests assume ("env vars in, platform default out"), so **the
   override needs its own cross-language parity test or m10's guarantee
   silently narrows** to "only the default path is proven to agree."
2. **A first-run UI surface.** None exists anywhere in the repo. The server
   cannot render `/ui/` before its root is fixed, so the Tauri window is the
   only plausible host — and the supervisor crate has no window-content
   surface beyond lifecycle plumbing.
3. **Detection and adoption** of an existing root (notebooks registry,
   `corpus-version.json`, LanceDB dirs) reported before adoption.
4. **A free-space check** that is honest on APFS (see below).

## The sequencing finding that constrains the picker

`main.rs` resolves `data_root` **before `tauri::Builder::default()` is
constructed** — before any app instance, any plugin, any window. Every
documented `tauri-plugin-dialog` call goes through `app.dialog()`, an
`App`/`AppHandle` method. **So the plugin structurally cannot be the first-run
picker** without restructuring `main()`'s sequencing.

brief-2 found `rfd` as the one path needing no restructuring, at the cost of a
new pinned dependency. That is a real decision with a real trade — restructure
the supervisor's startup ordering, or add a dependency — and it belongs in a
recorded decision, not inside an implementation diff. Same reasoning that made
m15's ADR worth writing before the code.

**One thing this simplifies:** no sandbox entitlement exists anywhere under
`apps/desktop`, so security-scoped bookmarks — which a sandboxed app would
need to retain access to a user-chosen directory across launches — are the
wrong mechanism here. A stored path suffices. Worth stating in the ADR so a
later sandboxing decision knows it invalidates this.

## AC4 is not measurable as written

`shutil.disk_usage()` on APFS **over-reports free space** (~30% in brief-2's
cited source) because purgeable space and snapshots are counted as available.
m11's AC says free space is "measured against a stated requirement … and the
shortfall is named in the refusal." A number that can be 30% wrong in the
optimistic direction cannot support a refusal.

The honest form is a stated requirement with headroom plus lower-bound
language, or a native `NSFileSystemAvailableSize`-style call. Either way the
AC needs rewording to claim what the measurement supports — the same
correction m15's AC3 needed.

## The inherited obligation, assessed

m15's AC3 was narrowed to what its gate measures, and the roadmap records the
full double-click-to-ready-server proof as m11's. Assessment: m11 **can**
discharge it — it is the first milestone that needs a launching application
for its own purpose — but it costs the `requires_bundled_model` prerequisites
(~4.6 GB of real weights from the operator's external HF cache) and makes
m11's gate depend on them. That is a scope decision, not a technical
obstacle.

## Estimated size

~1,200 LOC across ~14 files: the pointer artifact and its cross-language
parity test (~250), the Rust-side override read and its tests (~150), the
first-run UI surface (~350, entirely new), detection/adoption (~200),
free-space (~100), docs and ADR (~150).

**The roadmap's `M` is wrong.** This is `L` at least, and it contains two
decisions (persistence mechanism, picker mechanism) plus an unmeasurable AC.
Calibration: m10 estimated ~520 and measured ~1,227; m15 estimated ~900 and
measured 3,308.

## Open questions (max 5)

1. Persistence mechanism for the root pointer — plain file at a fixed
   OS-standard location vs `CFPreferences`/`NSUserDefaults` plist. Must be
   readable from Rust before Tauri starts AND from Python.
2. Picker mechanism — restructure `main()` so a Tauri plugin can run, or add
   `rfd`. Trade: startup-sequencing risk against a new pinned dependency.
3. Does m11 take on m15's inherited launch proof, with the ~4.6 GB model
   prerequisite it drags into m11's gate?
4. AC4's free-space claim needs rewording to what APFS can support.
5. Complexity re-rated `M` -> `L`; `allow_large_diff` should be set at init
   for the implementation dispatch, not retrofitted (the omission that
   produced an H2 finding in both m8 and m10).

## external_writes_required

- `git push origin main` — the only one. No package publish, no deploy, no
  mutating API call.
