# ADR — data-root selection: pointer persistence and first-run picker (desktop-distribution-m11)

**Status:** Proposed — awaiting owner acceptance (see "Owner approval record")
**Date:** 2026-08-12 · **Owner:** Chris Dare (per OWNERS.md)
**Roadmap item:** `desktop-distribution-m11` (`plans/desktop-distribution-roadmap.md`;
description premise corrected 2026-08-12 after Phase 1 research, AC8 asks for exactly this
document)
**Measurement anchor:** every repo fact below was re-read at `ea06449` in a worktree, not
quoted from the briefs.
**Source briefs:**
`.claude/notes/milestones/desktop-distribution-m11/research/brief-1.md` (explore — repo facts),
`.claude/notes/milestones/desktop-distribution-m11/research/brief-2.md` (general — external
sources with URLs and content hashes),
`.claude/notes/milestones/desktop-distribution-m11/research/synthesis.md`
**Prior record this ADR consumes:** `.claude/docs/adr-desktop-bundle-assembly.md` (m15 — the
shape this repo expects of a decision record, and the standing constraint that a decision may
be superseded by measurement), and m10's cross-language parity matrix in
`tests/test_desktop_self_authored_launch.py`.

This ADR decides **two things and nothing else**: where the operator's data-root choice
persists, and how the first-run picker is presented. It implements neither. The pointer
artifact, the Rust and Python override reads, the first-run dialogs, adoption detection and
the free-space gate all land in a separate implementation dispatch that inherits these
decisions. Recording them outside that diff is deliberate: both are expensive to reverse once
`main()`'s ordering, a cross-language parity row and an operator-facing on-disk artifact have
been written against them.

## Context and problem statement

- **The milestone's original mechanism does not exist.** The roadmap said the selection
  "persists through `OperatorSettingsStore`". That store's database is
  `<data_root>/cache/notebooks.db` (`server/application_paths.py` `_LAYOUT`;
  `server/operator_settings.py` `_resolve_db_path`). A store inside the data root cannot
  record where the data root is. This is a genuine ordering cycle, and the roadmap now says
  so. Everything below starts from there.
- **The decision point is in Rust, before Python and before Tauri.** `main()` calls
  `load_plan()` at `apps/desktop/crates/supervisor/src/main.rs:667`;
  `tauri::Builder::default()` is not constructed until `:716`. In the self-authored arm,
  `self_authored_plan` (`:512-533`) calls `platform_data_root(lookup)` (`:210-233`)
  **unconditionally** — there is no read of any operator preference anywhere in that file.
  So an operator-chosen root has no path at all into a double-clicked `.app` today.
- **`ARXMCP_DATA_DIR` is not the answer.** It is Python-side only, it is absent from
  `main.rs` entirely, and a double-clicked `.app` carries no shell environment. It is the
  dev/smoke knob that m10's self-authored arm exists specifically to not require.
- **Python already has the hook; Rust has none.** `ApplicationPaths.resolve` accepts
  `platform_default: Callable[[], Path] | None` (`server/application_paths.py:120`) and the
  installed-mode branch calls `(platform_default or (lambda: _platform_data_root(env)))()`
  (`:141`). The Python-side change is a new resolver behind an existing parameter. The Rust
  side has no equivalent seam and must grow one.
- **The app is not sandboxed.** Zero matches for `app-sandbox` or `entitlement` across
  `apps/desktop/**/*.{json,toml,rs,plist}` excluding `target/`, and no `.entitlements` file
  anywhere under `apps/desktop/` (re-measured at `ea06449`). This changes which persistence
  mechanisms are even applicable — see R2.

## Evidence ledger

Per §4.9, each row carries its own status and **nothing is upgraded from what its source
actually establishes**. brief-2 marks several as community-claimed; they stay that way. One
row (E7) is load-bearing for Decision 2 and is *not* in the evidence base at all, which is
recorded rather than smoothed over.

| # | Source | sha256 (fetched 2026-08-12 by brief-2) | What it establishes | Status |
|---|---|---|---|---|
| E1 | `https://v2.tauri.app/plugin/dialog/` | `649531a2de5e7c1e4eca7783a133930208653d3a2a8347d01045bd1bbbc669c0` | Every documented `tauri-plugin-dialog` call goes through `app.dialog()` — an `App`/`AppHandle` method; no documented path invokes it before Tauri's app exists | Documented (vendor) |
| E2 | `https://developer.apple.com/documentation/professional-video-applications/enabling-security-scoped-bookmark-and-url-access` | `f17b43c881b5c1bd662941d1baa11dcdb2fd438b1ce83cfb206ef55efe2904cd` | Security-scoped bookmarks exist to give a **sandboxed** app persistent access to a user-picked location across launches | Documented (vendor) |
| E3 | `https://developer.apple.com/documentation/foundation/userdefaults` | `4cbdc91b1ec26e9098f1ee66a488b9ceab12e09cd0aad3e1a5ea5eed644d94ab` | `UserDefaults`/`CFPreferences` is Apple's standard mechanism for small pre-bootstrap app state, keyed by bundle identifier, independent of any app-data directory | Documented (vendor) |
| E4 | `https://www.pythontutorials.net/blog/find-free-disk-space-in-python-on-os-x/` | `3fafd0e638fe077e2fe14800bcbd1e34e1947879ebec84027c0a5f257c2afa38` | `statvfs`/`shutil.disk_usage` on APFS omit purgeable space, local snapshots and reserved storage; author's own measurement: 50 GB reported vs 35 GB in Finder | **Community-measured, single author.** One example, not a vendor formula |
| E5 | `https://eclecticlight.co/2020/04/09/where-did-all-that-free-space-go-on-my-apfs-disk/` | `52305d2f4d131a4ca85e3f88059f3de715d439c04326260fb43c4e0e65af95f1` | Independent corroboration of the same purgeable-space/snapshot mechanism | **Community**, corroborating E4's mechanism, not its magnitude |
| E6 | `https://raw.githubusercontent.com/obsidianmd/obsidian-help/master/en/Getting%20started/Create%20a%20vault.md` | `21ac1c3c3dc50a20d01cc128d86929badfc80ecc1cf50750115d04a11b1aef9b` | One shipped app presents create-new vs open-existing-folder at first run, and detects an established folder by a known marker (`.obsidian/`) | Documented (vendor), **single case, explicitly not a census** |
| E7 | `rfd` crate | — | That a native folder picker can be invoked with no `tauri::App` instance | **NOT ESTABLISHED BY THE EVIDENCE BASE.** brief-2 asserts this in prose; no URL and no hash accompany it. What *is* measured is only its absence: zero `rfd` references under `apps/desktop/**/*.{toml,rs}` excluding `target/` |
| E8 | Repo, read directly at `ea06449` | — | `main.rs:667` `load_plan()` precedes `:716` `tauri::Builder::default()`; `self_authored_plan:518` calls `platform_data_root` unconditionally; `ApplicationPaths.resolve` already takes `platform_default` (`:120`, used at `:141`); workspace pins are all `=` (`tauri = "=2.11.5"`, `serde_json = "=1.0.151"`, 8 direct pins); no sandbox entitlement anywhere under `apps/desktop/` | Measured |

**Explicitly NOT established by anything above:** that any single call on macOS returns a byte
count a multi-GB write is guaranteed to succeed with (brief-2 found no source claiming it, and
purgeable space can itself be evicted mid-write); that `rfd` in particular satisfies E7's
shape; that a picker invoked before `tauri::Builder` runs on the thread AppKit requires for a
modal panel. Decisions 2 and 3 are written so that none of these three is assumed.

## Decision 1 — the root pointer is a plain JSON file at the platform's own app directory

**The operator's choice persists in a single UTF-8 JSON file at
`<platform_data_root()>/data-root.json`** — i.e. `~/Library/Application Support/arXMCP/`
on macOS, `%LOCALAPPDATA%\arXMCP\` on Windows, `$XDG_DATA_HOME/arXMCP/` (or
`~/.local/share/arXMCP/`) on Linux — computed by the **same two functions that already
exist and are already pinned to each other**: `_platform_data_root` (Python,
`server/application_paths.py:81-89`) and `platform_data_root` (Rust, `main.rs:210-233`).

### The non-circularity criterion, stated precisely

The property that matters is **not** "the pointer lives outside the data root". It is:

> The pointer's *location* is a pure function of the process environment, and never of the
> pointer's own content.

`platform_data_root()` reads only `HOME`/`USERPROFILE`/`LOCALAPPDATA`/`XDG_DATA_HOME`. It
therefore resolves with no knowledge of the chosen root, which is the entire cycle m11 has to
break. Stating it this way matters, because the chosen location *is* inside the **default**
data root when the operator keeps the default — and that is harmless under this criterion,
while a location derived from the *chosen* root would not be, however far outside the default
it sat.

### Why this location rather than a sibling of it

A file at `platform_data_root().parent` (e.g. `~/.local/share/arXMCP-data-root.json`) would
sit outside the default root, but it strews an app-specific file into a directory many
applications share. `<platform_data_root()>/` is the directory this application already owns
on every platform. Reusing it costs **zero new path-derivation logic** in either language,
which is the point: the new cross-language parity surface is then purely about *ordering and
parse rules*, not about a second pair of path functions that could drift the way the first
pair nearly did.

**The cost, stated rather than buried:** the pointer dies with the default root. Anything that
deletes `~/Library/Application Support/arXMCP/` — an operator cleaning up, a future "reset my
data" affordance — takes the pointer with it, and the next launch is indistinguishable from a
first run. That is a real consequence and it is **not specific to this location**: an absent
pointer and a never-configured install are indistinguishable under every option considered
here, including E3's. What *is* specific is that the default root's own lifecycle can trigger
it, so:

- The implementation must treat `data-root.json` as configuration, not corpus state; no
  detection, adoption, initialization or reset path may enumerate it as data.
- The absent-pointer case is the first-run path by design (see the three-way rule).

### Format and write discipline

- A JSON object, not a bare path string: it carries a schema version so a later field is not a
  format break, and it avoids the encoding/trailing-newline ambiguity a bare-text file invites
  across two languages. `serde_json` is already a pinned workspace dependency (E8) and Python's
  `json` is stdlib, so this adds no dependency in either language.
- The stored path is **absolute and already canonical**. `ApplicationPaths.resolve`'s
  source-mode leniency toward relative `ARXMCP_DATA_DIR` (`:132-139`) must not be inherited by
  this flow: whatever the picker collects is resolved to an absolute path *before* it is
  written, and a pointer whose content is not absolute is a corrupt pointer.
- Writes are atomic: temp file in the same directory, flush, then `os.replace` / `fs::rename`.
  A partially-written pointer must not be reachable. Note CLAUDE.md §4.5's standing win32 caveat
  about `os.replace` under concurrency — irrelevant here (single writer, first run) but the
  reason it is irrelevant belongs in the implementation's comment, not in silence.
- **A root that failed selection is never written.** Validation — existence or creatability,
  writability, free space, containment — completes before the pointer is written, not after.

### The three-way read rule (both languages, identically)

| pointer state | behavior |
|---|---|
| **absent** | first run. Take the platform default as the offered value and present the picker. This is the only state that may fall back silently. |
| **present, unreadable or unparseable or non-absolute** | **REFUSE, loudly, naming the pointer's own path.** Do not fall back to the platform default. |
| **present and readable, target directory missing** | **Report it** and refuse to proceed silently; the operator re-chooses or restores. Never re-default. (This is AC6 verbatim.) |

**Why a corrupt pointer refuses rather than falling back.** Falling back looks safer and is
worse. A present-but-unreadable pointer is *evidence that a choice was made*. Treating it as
"no choice" starts a second, empty corpus at the default location while the operator's real
corpus sits untouched on another volume. The failure mode is not data loss — it is data
divergence, which is quieter, is discovered later, and is exactly the "silently re-defaulted"
outcome AC6 forbids, one level up the stack. Refusing costs the operator one legible error
naming a file path they can inspect.

### Where the read is inserted, in each language

- **Python** — inside the `installed`-mode branch only, as the resolver supplied through the
  existing `platform_default` parameter (`:120`, `:141`). Consequences, all deliberate:
  an explicit `root=` argument and `ARXMCP_DATA_DIR` continue to **win over the pointer**
  (they are the dev/smoke overrides, and m10's arm exists to not need them); **source mode is
  untouched** — a source checkout resolves `<repo>/var/arxmcp` and never consults the pointer,
  so every existing test's behavior is byte-identical; and the Python delta is a new resolver
  behind an existing seam, not a new parameter and not a re-ordering.
  The resulting precedence is: explicit `root=` → `ARXMCP_DATA_DIR` → source-checkout
  `var/arxmcp` → **pointer** → platform default.
- **Rust** — in `self_authored_plan`, strictly ahead of the `platform_data_root(lookup)` call
  at `:518`. It stays inside `load_plan()`'s reach at `:667`, therefore still before
  `tauri::Builder::default()` at `:716`, which is the property the whole design turns on. An
  externally-supplied plan (`ARXMCP_DESKTOP_LAUNCH_PLAN`) continues to win outright — it is the
  test channel and this ADR does not touch it.

### The sandbox note this ADR is required to record

**No sandbox entitlement exists anywhere under `apps/desktop` today** (E8). A non-sandboxed
macOS process keeps ordinary POSIX access to a directory across launches with no bookmark
machinery, which is why Decision 1 can be a stored path at all (R2).

**Adopting App Sandbox later invalidates this.** A sandboxed build would start each launch in
a fresh container with no memory of prior grants, and a stored path would resolve to a
directory the process may not open. At that point Decision 1's *storage* survives but its
*sufficiency* does not: the pointer would additionally have to carry a security-scoped
bookmark blob, and the frozen Python child — a separate process that also opens the root —
would need its own answer. **Any future milestone that adds a sandbox entitlement must
re-open this ADR before it lands**, not after.

TCC-protected locations (Photos library, Mail, Time Machine volumes) are a separate and
narrower gate that applies regardless of sandboxing. An operator who picks one of those is a
corner case the implementation should surface as a distinct, actionable message, not a
redesign.

## Decision 2 — `main()`'s startup ordering is not restructured in m11; the picker is a pre-Tauri native dialog

**The first-run picker runs before `load_plan()`, from a native dialog that requires no
`tauri::App` instance. `main()`'s existing sequencing is left intact.**

E1 establishes that `tauri-plugin-dialog` cannot do this: every documented call is an
`App`/`AppHandle` method, and E8 measures that the data root is resolved 49 lines before the
builder exists. The plugin is therefore only available *after* restructuring. So the real
decision is restructure-versus-not, and this ADR decides **not**, for m11.

**Why the ordering is the expensive side of the trade.** `main()`'s sequencing is the surface
m5, m6 and m10 all gate: single-instance lock acquisition relative to window setup, the
barrier-env test hook, the self-authored-vs-external plan duality, and `test_hide_window`'s
smoke-only gating all sit downstream of where `data_root` is resolved. m6's fault matrix and
m10's self-authored-launch module were both hardened by adversarial critique against *this*
ordering. Inserting a window-bearing phase ahead of plan resolution does not merely add code —
it invalidates the premise those gates were written against, and honestly re-establishing them
means re-running a fault matrix, not adding a happy-path test. Against that, a new pinned
dependency costs one `Cargo.toml` line, one `Cargo.lock` entry, and a transitive tree to
review.

**What this decision does NOT do:** it does not name a crate as settled. brief-2 proposes
`rfd`, and E7 records that the evidence base contains **no citation for it** — only a measured
absence from this repo. Upgrading that to a decision would be exactly the move §4.9 forbids.
The implementation dispatch therefore:

1. verifies against the crate's own documentation that it can be invoked with no `tauri::App`
   and that its main-thread requirement is satisfied at the top of `main()` (macOS's modal
   panel requirement is a real constraint and is **unverified here**);
2. reviews its transitive tree, including the Linux backend question — a GTK-linked backend
   and an XDG-portal backend are materially different portability commitments, and Linux is a
   claimed portability target with no runner to exercise it (CLAUDE.md; m15's ADR §per-OS);
3. pins it with `=` like every one of the 8 existing direct workspace pins (E8), with a
   matching `Cargo.lock` entry — "unpinned" is ruled out here exactly as m15 ruled it out for
   `tauri-cli`;
4. **escalates rather than improvises** if (1) or (2) does not hold. The named fallback is R6,
   and it is a re-opening of this decision, not an implementation detail.

**What the dependency actually costs at runtime, which is less than it looks.** The picker
executes only when the pointer is absent — one branch of one launch in the life of an install.
Every subsequent launch reads a JSON file and calls nothing from the dialog crate. The cost is
in the supply chain and the review, not in the steady state.

**Sufficiency of native dialogs for the ACs.** AC1's default-or-choose and AC2's
report-then-adopt (notebook count and corpus version reported *before* adoption, with
initialization-over-existing-state requiring a distinct explicit act) are expressible as a
short sequence of native folder-pick and message dialogs carrying text. That is plain, and it
is enough. It is **not** a rich first-run window, and this ADR does not pretend the two are
equivalent — see R6.

**`tauri-plugin-dialog` is not disqualified generally.** A later in-app "change data location"
affordance runs after startup, inside a window, with an `AppHandle` in hand. E1 rules the
plugin out for the *first-run pre-Tauri* moment only.

## Decision 3 — the free-space check is a lower bound and must be phrased as one

**Whatever primitive measures free space, the number it produces is reported as a lower bound,
and the refusal says so. No refusal, message or document may present it as an exact figure or
a guarantee that a write will succeed.**

E4 and E5 establish — community-measured, one magnitude from one author, corroborated as to
mechanism — that `statvfs`/`shutil.disk_usage` on APFS count purgeable space, local snapshots
and reserved storage as available. The error is **asymmetric and optimistic**: the call reports
*more* space than is reclaimable, so it produces false "looks fine" outcomes, never false
refusals. A number that can be optimistic by roughly a third cannot, unqualified, carry the
sentence "you do not have room for this" — which is what the roadmap's AC4 now says in as many
words.

Either arm of AC4 satisfies this decision:

- `shutil.disk_usage()` with the stated requirement set with **headroom**, and lower-bound
  phrasing in the refusal. Cheapest, stdlib, cross-platform, matches this repo's posture.
- A platform call that excludes purgeable space (`NSFileSystemAvailableSize` via a native call
  from the supervisor, which already links macOS frameworks). Closer to what Finder shows —
  which is **community-claimed, not a vendor guarantee**, and brief-2 found *no* source
  claiming any call returns a byte count a write is guaranteed to succeed with. Adopting it
  therefore **does not license dropping the lower-bound phrasing**, and it must not be treated
  as buying precision it has not been shown to have.

The mechanism is the implementation's to choose. The phrasing is not.

Note the platform asymmetry when writing the message: Linux `statvfs` and Windows
`GetDiskFreeSpaceEx` do not carry this ambiguity class. Uniform lower-bound phrasing is
still the right call — a per-OS split in how honestly a refusal is worded is a worse artifact
than a uniformly conservative one.

## The cross-language parity obligation this creates

m10 pinned Rust's `platform_data_root` to Python's `_platform_data_root` by **running both**,
row for row, over an env matrix (`tests/test_desktop_self_authored_launch.py`). That matrix
proves agreement about *the default path*. Decision 1 inserts a read **ahead of** that function
in both languages, which is precisely the position both parity tests currently assume is empty.

**Therefore: the pointer read gets its own executable cross-language parity row, or m10's
guarantee silently narrows** to "only the default path is proven to agree" — and narrows
without any test turning red, which is the failure mode worth naming. The rows the
implementation owes, at minimum:

1. **Location parity** — both languages derive the same `data-root.json` path from the same
   environment, across the same `HOME`/`USERPROFILE`/`LOCALAPPDATA`/`XDG_DATA_HOME` branches
   the existing matrix already enumerates. (Reusing `platform_data_root()` is what keeps this
   row cheap; it is the same function, one `join` further on.)
2. **Three-way rule parity** — absent, corrupt, and target-missing produce the same *class* of
   outcome in both languages: default-and-prompt, refuse, report-and-refuse. Message text need
   not be byte-identical; the outcome class must be.
3. **Precedence parity** — a set env override still wins over a present pointer, in both.

m10's one deliberate divergence (Python falls back to `Path.home()` when no `HOME`/
`USERPROFILE` is set; Rust refuses) is **inherited unchanged** and must not be quietly widened
by the new code path.

## Rejected alternatives

**R1 — `OperatorSettingsStore` / `notebooks.db`** (the roadmap's original premise). Rejected as
circular, by measurement: `_resolve_db_path` falls back to
`ApplicationPaths.resolve().notebooks_db` = `<data_root>/cache/notebooks.db`. You cannot open
the file that names the data root by first knowing the data root. The store remains correct for
preferences scoped to an *already-selected* root (e.g. "don't show me this adoption prompt
again"), which is the use its docstring anticipates.

**R2 — security-scoped bookmarks.** Rejected: they solve App Sandbox's problem (E2), and this
app has no sandbox entitlement (E8). Adopting them means adopting App Sandbox first — a far
larger decision that would also constrain what the frozen Python child may touch on disk, its
network egress and its subprocess spawning, none of which m11 asks for. Recorded as the
mechanism that becomes *required* if sandboxing is ever adopted (Decision 1, sandbox note).

**R3 — `CFPreferences` / `NSUserDefaults`** (`~/Library/Preferences/com.arxmcp.desktop.plist`;
the bundle identifier already exists in `tauri.conf.json`). Rejected, and it is the strongest
rejected option. E3 makes it Apple's documented mechanism for exactly this class of small
pre-bootstrap state, and its advantages over Decision 1 are real: it survives some operator
reset flows that would take the default root with them, and it inherits `Preferences/`'s
OS-level backup semantics. It loses on two counts. First, from Rust it needs either a
`CFPreferences`/`objc2` FFI call or a plist crate — machinery Decision 1 does not need, in the
one language that must read the value earliest. Second and decisively, it is **macOS-only**:
Windows and Linux would need a second mechanism, so the parity obligation above would be owed
over *two* implementations instead of one, in a repo whose Windows and Linux desktop paths have
no runner to catch the drift. A cross-platform plain file is one artifact to keep honest.

**R4 — `ARXMCP_DATA_DIR` alone.** Rejected: it does not survive a double-click, which has no
shell environment, and it does not exist in `main.rs` at all (E8). Retained unchanged as the
higher-precedence dev/smoke override.

**R5 — a launch-plan-seed JSON at a well-known path** (brief-2's option 3). Rejected: it is
Decision 1 wearing the `Plan` abstraction's clothes, for no gain, and it conflates the
test/override channel (`ARXMCP_DESKTOP_LAUNCH_PLAN`) with a persisted operator preference. Two
channels that fail differently should not share a shape.

**R6 — restructure `main()` and use `tauri-plugin-dialog`.** Rejected **for m11**, not on
merit. It is the path to a real first-run window rather than a sequence of native dialogs, and
E1 makes the plugin the supported way to get one. It is rejected here because it invalidates
the ordering premise m5/m6/m10's gates were written against, and paying that cost for UI polish
in the same milestone that introduces a new on-disk artifact and a new parity row concentrates
too much risk. **This is the named revisit path**, and Decision 1 is orthogonal to it: the
pointer artifact is unaffected by where the picker runs, so a later milestone can restructure
`main()`, adopt the plugin, and retire the Decision 2 dependency without touching the
persistence format or the parity rows.

**R7 — host the first-run picker in the server's `/ui/` console.** Rejected by measurement: the
console is server-rendered, and `server.main.create_app`'s lifespan resolves `ApplicationPaths`
at startup — by the time `/ui/` can render anything, the root is already fixed. `bootstrap_mode`
does not help: it lets the server boot with *no corpus*, having already settled *which
directory* the root is. Different problem.

## Per-OS consequence

The portable invariant this ADR commits to is:

> The pointer is one file, one format, at a location both languages derive from the process
> environment alone, on every platform the app claims — with no per-OS mechanism split.

- **macOS** (`.app`, the only exercised target): `~/Library/Application Support/arXMCP/data-root.json`.
- **Windows** (portability target, no runner): `%LOCALAPPDATA%\arXMCP\data-root.json`. Derived,
  not exercised — `make desktop-conformance` is macOS-only (issue #423), so parity here rests on
  the cross-language matrix, which runs the branch without running the OS.
- **Linux** (portability target, not release-supported): `$XDG_DATA_HOME/arXMCP/data-root.json`,
  falling back to `~/.local/share/`. Same status. Decision 2's dialog-backend question (GTK vs
  portal) is the one place where the picker is *less* portable than the pointer, and it is
  called out as an implementation obligation rather than assumed away.

This ADR does not claim per-OS parity is *exercised*. It claims the chosen mechanism does not
require a per-OS split to be written — which is a weaker and true statement, and is the main
reason R3 lost.

## What this ADR deliberately does NOT decide

So the implementation dispatch inherits a bounded problem:

1. **The pointer file's JSON schema** — field names, the schema-version field's spelling, and
   whether anything beyond the path is stored. Decision 1 fixes the location, the format family,
   the absoluteness rule, the atomic-write discipline and the three-way read rule; not the keys.
2. **The picker crate.** Decision 2 fixes the *shape* (pre-`load_plan()`, no `tauri::App`, `=`
   pinned) and the escalation path; it does not name a crate as settled (E7).
3. **The free-space mechanism** — `shutil.disk_usage` with headroom, or a purgeable-excluding
   platform call. Decision 3 fixes the phrasing, not the call.
4. **The stated free-space requirement itself** (how many bytes, with what headroom multiple).
   Nothing in the evidence base fixes this number.
5. **The adoption-detection predicate.** The primitives exist (`NotebooksStore`,
   `_safe_read_corpus_version`, the `index/lancedb/*/corpus-version.json` and `index/kuzu/`
   markers) and E6 supplies one shipped precedent for the UX shape; which markers constitute
   "already carries arXMCP state", and what is reported, is the implementation's.
6. **The wording of every operator-facing message**, beyond Decision 3's binding lower-bound
   rule and Decision 1's requirement that a refusal name the pointer's path.
7. **Test module layout, marker choice and Makefile wiring** for the new parity rows.
8. **Whether m11 also discharges m15's inherited launch proof** (the roadmap's AC9, which brings
   `requires_bundled_model`'s ~4.6 GB prerequisites into m11's gate). That is a scope decision
   for the owner and the orchestrator, not a mechanism decision, and it is untouched by
   anything above.

## Consequences

- The repo gains its **first configuration artifact that is not data-root-relative**. That is a
  new category, and the rule that keeps it honest is the non-circularity criterion in Decision 1,
  not the specific path. Future state with the same bootstrap-ordering property belongs in this
  file or beside it — never back inside the root.
- `platform_data_root()` / `_platform_data_root()` become **load-bearing for two things**: the
  default data root and the pointer's location. Their existing parity matrix protects both, which
  is the payoff for reusing them, but it also means a future change to either function moves the
  pointer for every existing install. Any such change is a migration, not a refactor.
- The supervisor grows its **first read of operator state**. Until now `main.rs` read only
  environment variables and its own on-disk layout. That is a widening of what the pre-Tauri
  phase depends on, and the corrupt-pointer refusal is what keeps the widening legible.
- **m10's parity guarantee is preserved by construction or not at all.** There is no partial
  version: either the new rows exist and the guarantee still reads "the resolution order agrees",
  or they do not and it quietly means "the default agrees".

## How this ADR gets amended

m15's ADR was superseded by measurement the same day it was accepted, and that was the ADR
working, not failing. The equivalent triggers here, named in advance so the implementation
escalates instead of improvising:

- **Decision 1** is re-opened if a sandbox entitlement is adopted (a stored path stops being
  sufficient), or if the pointer's location is measured to be unreadable at the point
  `self_authored_plan` needs it.
- **Decision 2** is re-opened if the verification in its step (1) or (2) fails — no suitable
  crate, or an unacceptable transitive/portability commitment. R6 is the recorded fallback.
- **Decision 3** is not re-opened by finding a better measurement. A more accurate call changes
  the number; the lower-bound phrasing stands until a source establishes a guarantee, and
  brief-2 found none.

An amendment supersedes in place, as Decision 2a did: the superseded text stays, unedited, with
the measurement that killed it recorded above it.

## Owner approval record

**PENDING.** This ADR is Proposed. No implementation may proceed on Decisions 1, 2 or 3 until
the owner (Chris Dare, per OWNERS.md) records acceptance here. The implementation dispatch is
deliberately separate from this document for that reason.

Two items carry the most risk of being silently assumed away and are called out for the review:

- **Decision 2 names no crate.** If the implementation returns with a pin, the review question
  is whether E7's gap was actually closed against the crate's own documentation — not whether
  the code works on this box.
- **The parity rows are the deliverable, not a test detail.** A diff that adds the pointer read
  without adding rows 1–3 leaves m10's guarantee narrowed with every gate still green. That is
  the specific outcome this section exists to prevent.
