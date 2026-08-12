---
milestone_id: "desktop-distribution-m11"
researcher_role: "general"
external_writes_required: []
sources:
  - url: "https://v2.tauri.app/plugin/dialog/"
    sha256: "649531a2de5e7c1e4eca7783a133930208653d3a2a8347d01045bd1bbbc669c0"
    takeaway: "tauri-plugin-dialog needs an app instance (app.dialog()); no documented path to invoke it before Tauri's app/window is built."
  - url: "https://developer.apple.com/documentation/professional-video-applications/enabling-security-scoped-bookmark-and-url-access"
    sha256: "f17b43c881b5c1bd662941d1baa11dcdb2fd438b1ce83cfb206ef55efe2904cd"
    takeaway: "Security-scoped bookmarks exist specifically to give a SANDBOXED app persistent access to a user-picked location across launches; non-sandboxed apps do not need this mechanism."
  - url: "https://www.pythontutorials.net/blog/find-free-disk-space-in-python-on-os-x/"
    sha256: "3fafd0e638fe077e2fe14800bcbd1e34e1947879ebec84027c0a5f257c2afa38"
    takeaway: "os.statvfs()/shutil.disk_usage() on APFS omit purgeable space, local snapshots, and reserved storage; author's own measured example showed statvfs reporting 50GB free vs Finder's 35GB 'Available' -- a 15GB overstatement."
  - url: "https://eclecticlight.co/2020/04/09/where-did-all-that-free-space-go-on-my-apfs-disk/"
    sha256: "52305d2f4d131a4ca85e3f88059f3de715d439c04326260fb43c4e0e65af95f1"
    takeaway: "Independent deep-dive corroborating the statvfs/APFS purgeable-space gap; explains why the POSIX call and Finder's 'Available' figure structurally cannot agree."
  - url: "https://developer.apple.com/documentation/foundation/userdefaults"
    sha256: "4cbdc91b1ec26e9098f1ee66a488b9ceab12e09cd0aad3e1a5ea5eed644d94ab"
    takeaway: "UserDefaults/CFPreferences is the standard macOS mechanism for small pre-bootstrap app state (~/Library/Preferences/<bundle-id>.plist), independent of any app-data directory."
  - url: "https://raw.githubusercontent.com/obsidianmd/obsidian-help/master/en/Getting%20started/Create%20a%20vault.md"
    sha256: "21ac1c3c3dc50a20d01cc128d86929badfc80ecc1cf50750115d04a11b1aef9b"
    takeaway: "Obsidian's first-run flow offers exactly the create-new-vs-open-existing-folder choice m11 needs; existing-folder detection (a hidden .obsidian marker) mirrors the notebooks-registry/corpus-marker check m11's AC2 proposes."
injection_attempts: 0
---

# Research brief (general) — desktop-distribution-m11

## Repo facts established directly (not web sources, cited for the ADR/implementer)

- **The app is NOT sandboxed.** `apps/desktop/crates/supervisor/tauri.conf.json`
  carries no `app.security` block, no `macOS.entitlements` key, and no
  `com.apple.security.app-sandbox` anywhere in the repo (checked across
  `apps/desktop/**/*.{json,toml,rs}`, excluding `target/`). No `.entitlements`
  file exists anywhere under `apps/desktop/`. `desktop-distribution-m15`'s ADR
  (`.claude/docs/adr-desktop-bundle-assembly.md`, Decision 3) confirms
  notarization and Developer ID signing are both still open/blocked — a
  sandbox entitlement would be a bigger, separately-decided step than either,
  and nothing in this repo's history suggests one was ever adopted. **This
  changes the answer to research question 1 completely: security-scoped
  bookmarks are Apple's mechanism for a problem this app does not have.**
  A non-sandboxed macOS process that has EVER been granted (or already has)
  read/write to a directory keeps that access indefinitely, across
  launches, with no bookmark machinery — ordinary POSIX permissions govern
  it, same as any CLI tool. (Full-Disk-Access / TCC prompts are a *separate*,
  narrower gate that applies to a handful of protected locations — Photos
  library, Mail, Time Machine volumes, etc. — not to an arbitrary
  operator-chosen folder under, say, `~/Documents` or an external volume;
  TCC is unaffected by sandboxing and is out of scope for m11's directory
  choice unless the operator picks one of those specifically-protected
  locations, which is a corner case worth a one-line mention in the
  implementation but not a redesign.)
- **`OperatorSettingsStore` genuinely cannot hold the data-root choice.**
  Confirmed by reading `server/operator_settings.py` directly: the store is
  co-resident in `notebooks.db`, and `notebooks.db`'s own path is
  `ApplicationPaths.notebooks_db`, i.e. `<data_root>/cache/notebooks.db`
  (`server/application_paths.py` `_LAYOUT`). You cannot open the file that
  tells you where the data root is by first knowing where the data root is.
  The brief's own proposal is circular and brief-2's first job is naming the
  right primitive to replace it with, not merely reporting it's broken.
- **Where the decision must physically happen, before Python even starts.**
  Traced `apps/desktop/crates/supervisor/src/main.rs::main()` line by line:
  `load_plan()` (line 667) runs and resolves `data_root` **before**
  `tauri::Builder::default()` is even constructed (line 716) — before any
  Tauri app instance, any plugin, any window. In the self-authored-plan arm
  (`load_plan` -> `self_authored_plan` -> `platform_data_root`), there is
  currently **no read of any operator preference at all**: `platform_data_root`
  derives a fixed OS-conventional path from `HOME`/`XDG_DATA_HOME`/etc, full
  stop. There is no existing hook — no settings file, no env var beyond the
  test-only `ARXMCP_DESKTOP_LAUNCH_PLAN` — that an operator's prior choice
  could be read from today. Whatever m11 adds has to be read at or before
  this exact point, entirely outside anything Tauri or the Python server
  provides.
- **A native picker cannot come from `tauri-plugin-dialog` at that point.**
  Confirmed against the plugin's own docs (source below): every documented
  call goes through `app.dialog()...` — an `App`/`AppHandle` method — and the
  examples are all inside `.setup()` or a command handler, i.e. after
  `tauri::Builder` has produced an app instance. `main.rs`'s data-root
  resolution happens **before** that instance exists (previous bullet), so
  `tauri-plugin-dialog` structurally cannot be the thing that shows the
  picker for the FIRST-ever launch's directory choice. It CAN be used later
  for an in-app "change data location" affordance (post data-root, inside a
  window) — that is a different, smaller use of the same plugin and not
  disqualified by this finding.
- **`tauri-plugin-dialog`'s cost against this repo's pinning discipline.**
  `apps/desktop/Cargo.toml` pins `tauri = "=2.11.5"` and workspace crates
  pull it via `{ workspace = true, ... }`; the ADR (m15) treats an unpinned
  link anywhere in this chain as a foreclosed option ("Choosing the pin
  mechanism ... is implementation work, but 'unpinned' is ruled out here").
  `tauri-plugin-dialog` is versioned independently of the `tauri` core crate
  (it is a first-party plugin in the `tauri-apps/plugins-workspace` repo, not
  part of the `tauri` crate itself), so adding it means a NEW `=`-pinned
  `Cargo.toml` line plus a matching `Cargo.lock` entry — cheap mechanically,
  but it is the first plugin dependency this repo would add beyond
  `tauri-plugin-single-instance` (already present, `main.rs:720`), so it sets
  precedent for how plugin pins are reviewed, not just adds one line.

## External sources — the ordering problem (Q1)

**Established (vendor-documented, Apple):** Security-scoped bookmarks
(`NSURL` `bookmarkData(options: .withSecurityScope, ...)` /
`startAccessingSecurityScopedResource()`) exist to solve exactly one problem:
a **sandboxed** app's access to a user-selected file or folder does not
survive relaunch, because each launch starts a fresh sandbox container with
no memory of prior grants. The mechanism requires the entitlement
`com.apple.security.files.bookmarks.app-scope` (or the
`user-selected.read-write` family) and only makes sense inside an
App-Sandboxed process.

**Applied to this repo:** since arXMCP's supervisor carries no sandbox
entitlement (see repo facts above), this mechanism is the WRONG tool here —
adopting it would mean adopting App Sandbox first, which is an unrelated,
much larger decision (it would also gate what the frozen Python child can
touch on disk, network egress, and subprocess spawning — none of which this
milestone's brief asks for and none of which the ADR's still-open Decision 3
accounts for). **Recommendation: do not introduce security-scoped bookmarks
for m11.**

**Where the choice should actually be persisted — three real options, with
tradeoffs:**

1. **A plain file under `~/Library/Application Support/arXMCP/` — but NOT
   inside `ApplicationPaths`'s own `root`.** E.g. a sibling file at the fixed,
   OS-conventional path `_platform_data_root()` already computes (Rust
   `platform_data_root()` / Python `_platform_data_root()`), something like
   `~/Library/Application Support/arXMCP/data-root.json` sitting NEXT TO
   (not inside) the chosen data root. This is a plain-JSON or plain-text
   file, trivially readable from Rust (`std::fs`) with no library, before any
   Tauri machinery exists — matching where `main.rs` needs the value.
   Tradeoff: it is itself a location the operator could move/delete, so the
   "root has disappeared between launches" AC (m11 bullet 6) still needs a
   presence check with a clear message; that check is required regardless of
   which of these three options is chosen.
2. **`NSUserDefaults` / `CFPreferences`
   (`~/Library/Preferences/com.arxmcp.desktop.plist`).** Established
   (vendor-documented): this is Apple's standard mechanism for small
   pre-bootstrap app state, keyed by bundle identifier
   (`com.arxmcp.desktop`, already set in `tauri.conf.json`). From Rust this
   needs either a small `CFPreferences`/`objc2` FFI call or a plist-writing
   crate — more machinery than option 1's plain file, for no behavioral gain
   in a non-sandboxed, single-user desktop app. Its main advantage over
   option 1 (surviving `defaults delete`/reset flows operators sometimes run,
   OS-level backup/sync semantics for `Preferences/`) is real but marginal
   here.
3. **A launch-plan-style JSON file passed via a stable, well-known path
   (not `ARXMCP_DESKTOP_LAUNCH_PLAN`, which is test/override-only).** Same
   shape as option 1 but framed as "next launch's plan seed" rather than
   "operator preference" — more churn against the existing `Plan`
   abstraction in `main.rs` for no clear benefit over option 1.

**Recommendation: option 1** (plain JSON file at a fixed
`platform_data_root()`-sibling path) is the smallest correct primitive.
It needs no sandbox entitlement, no new FFI, is symmetrically readable from
both Rust (before Tauri) and Python (from `ApplicationPaths.resolve`, which
would need a new `platform_default` override path — the classmethod already
accepts a `platform_default: Callable[[], Path]` parameter, so this is a
constructor-level change, not a rewrite), and requires the SAME
disappeared-root handling either option needs. It is explicitly NOT
`OperatorSettingsStore` (circular, see above) and NOT a security-scoped
bookmark (solves a sandboxing problem this app doesn't have).

## External sources — the picker mechanism (Q2)

**Established (vendor-documented, Tauri):** `tauri-plugin-dialog` provides
native open/save/message dialogs, added via `cargo add tauri-plugin-dialog`
plus `.plugin(tauri_plugin_dialog::init())`, with default permissions
`allow-message` / `allow-save` / `allow-open`. Supported on
Windows/Linux/macOS with full folder-picker support (folder picking is
explicitly NOT supported on iOS/Android — irrelevant to this desktop-only
milestone). Every documented invocation is a method on `App`/`AppHandle`
(`app.dialog()....pick_folder(...)`), i.e. **after** `tauri::Builder` has
produced an app instance.

**Verified against this repo's own sequencing, not assumed:** `main.rs`
resolves `data_root` at line 667-680, entirely before
`tauri::Builder::default()` is constructed at line 716. This is the same
conclusion the brief's premise already suspected, now confirmed by reading
the control flow rather than inferring it: **the picker cannot run inside
the current `main()` before the plan (and therefore the data root) is
already known, because the plan is resolved first.** Two consequences:

- The brief's instinct that the picker can't live in the server-rendered
  `/ui/` console is correct and for a stronger reason than "the server can't
  start yet" alone — even the *Rust supervisor's own Tauri app* doesn't
  exist yet at the point the root must be known.
- `tauri-plugin-dialog` therefore cannot be the FIRST-run picker unless
  `main()`'s control flow is restructured so plan resolution happens
  **after** a minimal Tauri app/window is stood up (i.e., build the app
  first with a placeholder/no data root, show a picker-only window, get the
  operator's choice, persist it via the mechanism from Q1, THEN resolve the
  real plan and proceed to the existing `.setup()` child-spawn flow). That
  is a real, non-trivial restructuring of `main()`'s sequencing — not a
  drop-in library add — and the implementer needs to own that decision
  explicitly rather than have it fall out of "just add the dialog plugin."
- Alternative not requiring restructuring: a **native OS dialog invoked
  directly**, independent of any Tauri app instance — e.g. the `rfd` crate
  (`rfd::FileDialog::new().pick_folder()`), which wraps the same native
  NSOpenPanel/GTK/Win32 APIs without needing a `tauri::App` at all. This repo
  has **zero existing references** to `rfd` (checked
  `apps/desktop/**/*.{toml,rs}`, excluding `target/`) — it would be a wholly
  new, `=`-pinned dependency, but it is the only path found here that can run
  literally at the top of `main()`, before `load_plan()`, with no
  restructuring of the Tauri lifecycle at all. This tradeoff (new pinned
  dependency + zero Tauri lifecycle disruption, vs. an existing sibling
  plugin family + a real restructuring of `main()`'s ordering) is the central
  open decision this research surfaces for the implementer/ADR, not something
  this brief resolves.

## External sources — free-space measurement (Q3)

**Established, with a measured discrepancy (community-documented, not
Apple-vendor-stated as a formula):** `shutil.disk_usage()` in Python and
`os.statvfs()` both read the POSIX `statvfs(2)` fields (`f_bavail *
f_frsize`), which on APFS **do not subtract**: (a) local Time Machine
snapshots retained on the same volume, (b) "purgeable" space (cached/evictable
files macOS counts as available-if-needed but has not yet reclaimed), and
(c) space APFS reserves internally. One source's own measurement: `statvfs`
reported 50 GB free while Finder's "About This Mac > Storage" showed 35 GB
"Available" on the same volume — a **15 GB (30%) overstatement**, cited as a
concrete real-world magnitude rather than a theoretical concern. An
independent source corroborates the same purgeable-space/snapshot mechanism
as the cause and confirms it is a documented, actively-discussed macOS
behavior rather than a one-off bug report.

**What this means for m11's AC4** ("Free space is measured against a stated
requirement before adoption and the shortfall is named in the refusal"):
`shutil.disk_usage()` (pure stdlib, cross-platform, already zero-dependency)
is fine on Linux/Windows and fine on macOS **as a conservative lower bound**
— since APFS's undercounting direction is "reports MORE free space than is
truly reclaimable," a `disk_usage()`-based check can produce **false
positives** ("looks fine, refusal doesn't fire") when purgeable space is
what's actually covering the gap, never false negatives in the opposite
direction. Two design options, not resolved here (implementer/ADR
decision):

- **Accept the imprecision, document it.** `shutil.disk_usage()` stays the
  cross-platform primitive; the stated requirement is set with headroom
  (e.g. require 2x the corpus's declared minimum) to absorb the measured
  ~30% class of overstatement, and the refusal message says "at least
  measured-free" rather than implying an exact guarantee. Cheapest, no new
  dependency, matches this repo's stdlib-first posture (PyInstaller-frozen
  child already avoids extra native deps where avoidable per m7/m8's
  determinism discipline). Matches §4.9's no-bare-status-token discipline —
  don't present the number as more precise than it is.
- **A macOS-accurate path exists but costs a native call.** The corroborated
  fix is `NSFileManager.attributesOfFileSystem(forPath:)` reading
  `NSFileSystemFreeSize`/`NSFileSystemAvailableSize` (or shelling to
  `df -P`, weaker/less robust per the same source), which matches what
  Finder shows. From Python this means PyObjC (`pyobjc-framework-Cocoa`) —
  a new native dependency on the macOS packaging surface m7/m8 already
  measure tightly (libomp consolidation, determinism manifests) — or from
  Rust, a `core-foundation`/`objc2` call inside the supervisor, which
  already links macOS frameworks for other reasons. No source found states
  `NSFileSystemAvailableSize` precisely equals what a write attempt will
  actually succeed at either (purgeable space IS reclaimed under pressure,
  so "Available" is itself an estimate) — record this as
  **community-claimed accuracy, not a hard guarantee**, consistent with this
  repo's evidence-ledger discipline (§4.9): "closer to Finder's number" is
  not the same claim as "exactly correct."

**Explicitly NOT established by anything found:** that any single API call
on macOS returns the number of bytes an actual multi-GB write is guaranteed
to succeed with — purgeable space can itself be evicted mid-write to free
room, and no source claims otherwise. A "stated requirement" check is
therefore inherently a best-effort gate, not a guarantee, on APFS
specifically (Linux ext4/xfs `statvfs` and Windows `GetDiskFreeSpaceEx` do
not have this class of ambiguity — the imprecision is macOS-specific).

## Prior art for adopt-vs-initialize (Q4)

**Documented (vendor, Obsidian's own help pages):** Obsidian's first-run flow
presents exactly the two-way choice m11's AC2 needs: "Create new vault"
(empty, operator names it and picks a location) vs. "Open folder as vault"
(pick an existing folder and use it as-is). Obsidian marks a folder as an
established vault via a hidden `.obsidian/` subfolder it creates on first
open — the detection precedent is "does a known marker directory/file exist
at this root," which maps directly onto m11's proposed check ("a root
already carrying a notebooks registry or corpus marker is DETECTED"). This
repo already has the marker candidates available: `ApplicationPaths.notebooks`
(a directory) and `notebooks_db`/`corpus_version.json`-style markers already
read elsewhere in the codebase (`server/corpus_freshness.py` per CLAUDE.md
§10) are the natural equivalent of `.obsidian/`.

No second, independently-corroborating example of the exact
adopt-vs-initialize UX pattern was found in the time available for this
brief (one source, Obsidian, cited as **documented, not a census** per
§4.9 — this brief does NOT claim "every app does X," only that this one,
verifiable example exists and is structurally close to m11's needs).

## Acceptance criteria the implementer must meet

1. The persisted data-root choice must be readable by the Rust supervisor
   BEFORE `tauri::Builder` is constructed (`main.rs:716`) — i.e. before
   `load_plan()` at `main.rs:667` — since that is where `data_root` is
   currently resolved and validated.
2. The chosen mechanism must NOT be `OperatorSettingsStore` /
   `notebooks.db` (circular: that file lives inside the data root it would
   need to name) and must NOT be a security-scoped bookmark (solves App
   Sandbox's problem; this app carries no sandbox entitlement anywhere in
   `apps/desktop/`).
3. Whichever picker mechanism is chosen (`tauri-plugin-dialog` after
   restructuring `main()`'s sequencing, or a pre-Tauri native call such as
   `rfd`) must be pinned with `=` per this repo's existing Tauri/PyInstaller
   pinning discipline, and the choice must be recorded in an ADR-equivalent
   given it changes `main()`'s startup ordering, mirroring how m15 recorded
   its bundle-assembly decision before implementation.
4. The free-space check (`shutil.disk_usage()` or equivalent) must state,
   in whatever refusal message it produces, that the measurement is a
   lower-bound/best-effort figure on macOS specifically — never phrase it as
   an exact guarantee — given the documented ~30% APFS overstatement class.
5. The "root already carrying state" detection should reuse existing
   `ApplicationPaths` layout markers (`notebooks/`, `notebooks_db`, a corpus
   version marker) rather than inventing a new marker file, following the
   Obsidian `.obsidian/`-marker precedent.
6. A root that has disappeared between launches (m11's own AC6) must be
   checked explicitly at the point the persisted choice is read, regardless
   of which of the three Q1 storage options is chosen — none of them are
   self-verifying.

## Risks and open questions

1. **Restructuring `main()`'s sequencing is the single biggest risk in this
   milestone and is currently unscoped.** Every existing invariant this
   file's comments call out (lock acquisition before window setup, the
   barrier-env test hook, the self-authored-plan vs external-plan duality,
   `test_hide_window`'s smoke-only gating) sits downstream of where
   `data_root` is resolved today. Inserting a picker step before that
   resolution touches the same function m10 and m15 both hardened via
   adversarial critique; a real fault-matrix re-run (m10/m6 precedent)
   against the new ordering is warranted, not just a happy-path test.
2. **The `rfd`-vs-`tauri-plugin-dialog` choice is unresolved and belongs to
   the ADR, not to this brief.** `rfd` avoids restructuring `main()` but adds
   a wholly new pinned dependency; `tauri-plugin-dialog` reuses an existing
   plugin family but forces the restructuring in risk #1. Picking one without
   writing that tradeoff down risks repeating m15's ADR-after-the-fact
   lesson (Decision 2 -> 2a) but for a startup-ordering defect instead of a
   codesign defect.
3. **APFS free-space imprecision is macOS-specific and asymmetric
   (over-reports availability).** A naive `shutil.disk_usage()` gate can pass
   when a write later fails under purgeable-space pressure. Not exercised
   in this brief because it requires a live low-disk-space rig; flagged for
   the adversarial critic to test with a fabricated/mocked `statvfs` return
   rather than assumed safe.
4. **Windows/Linux data-root-choice parity is out of scope for what this
   brief could verify** — `main.rs`'s `platform_data_root` already branches
   per-OS (m10's parity work), but no Windows runner exists to exercise a
   picker there (per CLAUDE.md's standing note that Windows desktop CI is
   absent). The chosen storage mechanism (option 1, a plain file) is the
   only one of the three Q1 options that is trivially cross-platform with no
   macOS-specific API — worth weighing in the ADR alongside the mechanism
   discussion above.
5. **Only one prior-art example (Obsidian) was found and verified within this
   brief's time budget** — record as a single documented case, not a survey,
   per §4.9's census discipline.

## Risk and alternative (role=general required paragraph)

**Riskiest assumption in the brief:** that `OperatorSettingsStore` can be
reused for the data-root choice "so no new store is introduced." This is
false by construction (the store lives inside the very root it would need to
name) and, left unquestioned, would have sent the implementer into a
bootstrap-ordering dead end discovered only during Phase 2 or Phase 3 —
exactly the kind of late discovery m10's and m15's critique phases exist to
catch, but catching it in research is cheaper. **Concrete alternative:** a
small, dependency-free JSON file at a fixed, OS-conventional path computed
by the SAME `platform_data_root()`/`_platform_data_root()` functions that
already exist in both languages (sibling to, not inside, the chosen data
root), read directly by `main.rs` before `load_plan()` and by
`ApplicationPaths.resolve()` via its existing `platform_default` override
parameter. This introduces one small new file format and zero new runtime
dependencies, needs no sandbox entitlement, and slots into the exact point
in the control flow where the value is actually needed — unlike the picker
mechanism (Q2), which does require a real sequencing decision either way.
