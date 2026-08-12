# ADR — macOS application-bundle assembly for the desktop distribution (desktop-distribution-m15)

**Status:** Accepted 2026-08-12 · **amended same day** — Decision 2 superseded by Decision 2a
(payload location moved to `Contents/Resources/` after the assembled artifact proved `codesign`
cannot seal at the original location). Decisions 1 and 3 stand unchanged.
**Date:** 2026-08-11 · **Owner:** Chris Dare (per OWNERS.md)
**Roadmap item:** `desktop-distribution-m15` (`plans/desktop-distribution-roadmap.md`,
AC1 + AC2; AC text amended 2026-08-12 after Phase 1 research)
**Source briefs:**
`.claude/notes/milestones/desktop-distribution-m15/research/brief-1.md` (explore — repo
and toolchain facts),
`.claude/notes/milestones/desktop-distribution-m15/research/brief-2.md` (general — the
external evidence, with URLs and content hashes),
`.claude/notes/milestones/desktop-distribution-m15/research/synthesis.md`
**Prior record this ADR consumes:** `apps/desktop/README.md` § "Child payload layout and
its trust assumption" (written by `desktop-distribution-m10` as this ADR's input) and
`.claude/notes/milestones/desktop-distribution-m10/rectify/summary.md` § "What the fixes
do NOT close".

This ADR decides **where the frozen child payload lives inside a macOS `.app` and which
build actor puts it there**. It implements none of it: assembly, the combined build gate,
the `child_payload_root()` re-point and the re-pointed m7/m8/m9 guards land in a separate
implementation dispatch that inherits this decision. Recording the decision outside that
diff is deliberate — the layout is expensive to reverse once the guards, the Rust
resolver and the operator-facing README have all been written against it.

## Context and problem statement

- No `.app` has ever been produced by this codebase. `tauri.conf.json` carries
  `"bundle": {"active": false}` with no `resources` and no `externalBin`
  (`apps/desktop/crates/supervisor/tauri.conf.json`), and there is no `tauri-cli` entry
  in `apps/desktop/Cargo.lock` and no `.app`/`.dmg` output anywhere under
  `apps/desktop/`. Every first-run claim after m10 depends on this artifact existing.
- The payload is not a sidecar binary. It is m7's PyInstaller **onedir** — two
  executables (`arxmcp-desktop-child`, `arxmcp-desktop-probe`) plus a shared `_internal/`
  tree of hundreds of Mach-O `.so`/`.dylib` files, ~0.75 GB
  (`apps/desktop/pyinstaller/arxmcp_desktop.spec`, `desktop_package.py`; size class per
  CLAUDE.md §4.5).
- m10 committed to a **sibling-of-the-supervisor-executable** convention
  (`<supervisor dir>/arxmcp-desktop-child/arxmcp-desktop-child`, resolved by
  `child_payload_root()` at `apps/desktop/crates/supervisor/src/main.rs:311-316` and
  contained by `resolve_inside()` at `:247-268`, which refuses a symlinked root after
  m10's M13 fix). m10's own doc comment says m15 replaces that convention.
- The roadmap's original AC1 posed the mechanism as a choice among `bundle.resources`,
  `bundle.externalBin`, and the sibling convention. **Phase 1 research found that a false
  choice**, which is why the AC was amended and why this ADR treats the hybrid as
  first-class rather than as a fallback.

## Evidence ledger

Per §4.9's discipline, each row carries its own status. **Nothing below is upgraded from
what its source actually establishes**; brief-2 flags several as community-claimed and
they stay that way here.

| # | Source | sha256 (fetched 2026-08-11) | What it establishes | Status |
|---|---|---|---|---|
| E1 | `https://v2.tauri.app/develop/sidecar/` | `bbc36e085c552d4e520f049ef6f88374c7e26fc8d3895d963149ce7cfc1b09b0` | `externalBin` resolves exactly ONE executable per target triple (`name-$TARGET_TRIPLE`); no directory form is documented | Documented (vendor) |
| E2 | `https://v2.tauri.app/develop/resources/` | `6f2c5e15827e4da507c975cb92de4a5c2be3b1aba99620b21f3f8c4df40ddf0e` | `bundle.resources` DOES embed a whole directory, "preserving the original structures", into `$RESOURCE` | Documented (vendor) |
| E3 | `https://github.com/tauri-apps/tauri/issues/11992` | `432b6142a4581a8a1845476aa20c09b415631f14a5e30f500cab37ac4c168f87` | Notarization rejects the **main app binary** with an invalid-signature error *specifically when `externalBin` sidecars are present*; removing `externalBin` fixes it | Open, untriaged bug report (Tauri v2); no vendor fix as of fetch |
| E4 | `https://github.com/orgs/tauri-apps/discussions/12001` | `9c7e13e5b28ee19beee93e527d89566e9e3506d1bd320543edd06ec7bbee40a4` | dylibs shipped via `bundle.resources` are NOT signed by the Tauri build and fail notarization; the same dylibs via the macOS `frameworks` mechanism ARE signed and do notarize | **Community-confirmed, not vendor-documented.** The reporter calls their own `frameworks` route a workaround; scale is a handful of dylibs, not a Python closure |
| E5 | `https://raw.githubusercontent.com/tauri-apps/tauri-docs/v2/src/content/docs/distribute/macos-application-bundle.mdx` | `eebeb6d052990159229027e336ffcb3c0d92fdba480431af71dd392f1bad7def` | Canonical `.app` layout: `Contents/{MacOS,Resources,Frameworks,PlugIns,SharedSupport,_CodeSignature}`; custom dylibs are placed and signed via `frameworks`, not generic `resources` | Documented (vendor) |
| E6 | `https://github.com/pyinstaller/pyinstaller/issues/8927` | `01f027dc18b7b55337980a1c14f24384f9bd5090713161546846f7a21bc0a582` | A PyInstaller app notarizes as `--onefile` but **fails Apple's notary as `--onedir`** even when local `codesign --deep --strict` reports valid | Third-party report; precedent for the exact payload shape, not a vendor statement |
| E7 | Repo, read directly | — | `tauri = "=2.11.5"`, `tauri-build = "=2.6.3"` (workspace `Cargo.toml`, matched exactly in `Cargo.lock`); `bundle.active: false`; no `tauri-cli` in `Cargo.lock` | Measured 2026-08-11 |

**Explicitly NOT established by anything above:** where `externalBin` sidecars land inside
`Contents/` (brief-2 could verify no source; the community answer "`Contents/MacOS`" is
recorded as **unverified**); that pre-signing plus `resources` passes notarization; that
any layout in this ADR passes notarization. See Decision 3.

## Decision 1 — the hybrid is the chosen mechanism

**Tauri builds the `.app` shell only. `desktop_package.py` owns payload placement and
pre-signing. The outer bundle is re-sealed after placement.**

Concretely, the pipeline the implementation dispatch must build:

1. `desktop_package.py build` produces the onedir exactly as it does today (m7's
   determinism, `direct_url.json` sanitization and build-root scan unchanged, upstream of
   everything here).
2. A pre-signing step, owned by `desktop_package.py`, signs the payload's nested Mach-O
   files **bottom-up** — every `.so`/`.dylib` and both executables, not just the top-level
   launcher. `codesign --deep` is not that step and must not be substituted for it (E4,
   E6: `--deep` is exactly the shortcut whose local success did not survive the notary).
3. Tauri's bundler builds the shell with `bundle.active: true`, **no `resources`, no
   `externalBin`, no `frameworks` entry for the payload**. Its inputs stay what they are
   today plus the flip of `active`.
4. A post-bundle step copies the pre-signed payload tree into the bundle and re-seals the
   outer `.app`.

**Why the hybrid rather than a stock config key:** it is the only path in the evidence
base with no unresolved *mechanism* risk. Its cost is a bespoke assembly script this repo
must own and document; that cost is paid in implementation effort, which is recoverable,
where the rejected options' cost is an unfixable dependency on someone else's open bug.

## Decision 2 — SUPERSEDED 2026-08-12 by Decision 2a

> **Superseded by measurement, before anything else was built on it.** The
> implementation dispatch assembled the artifact and found `codesign` **cannot seal**
> a bundle at this location. It treats every file under `Contents/MacOS` as a nested
> code object and refuses the whole bundle at the first non-Mach-O one:
>
>     <app>: code object is not signed at all
>     In subcomponent: .../Contents/MacOS/arxmcp-desktop-child/_internal/tools/sbom.sh
>
> A PyInstaller onedir is ~5,300 files, most of them not Mach-O, so this is not
> reachable by signing more thoroughly. It is a property of the LOCATION, proved by an
> A/B control that builds two one-file `.app` trees differing only in where a six-byte
> `data.txt` sits: `Contents/MacOS/` is refused, `Contents/Resources/` seals and
> reports "valid on disk / satisfies its Designated Requirement".
>
> This is the condition **R3** names as the trigger for revisiting placement — reached
> by measurement on this host rather than by a notary submission, and therefore reached
> while m15 is still the only thing built on the layout. That is precisely what writing
> this ADR before the diff was for.
>
> The reasoning below is retained unedited, because its first argument — that
> `Contents/Resources` is where E4's unsigned-payload failure lives — is still true and
> is what Decision 2a must answer.

### Decision 2 as originally accepted (retained for the record)

**The payload goes to `Contents/MacOS/arxmcp-desktop-child/`**

The payload directory is placed **as a sibling of the supervisor executable inside
`Contents/MacOS/`**, preserving m10's convention verbatim rather than replacing it.

Two reasons, in order of weight:

1. `Contents/Resources` is where E4's failure lives. A PyInstaller `_internal/` tree is
   Mach-O **executable code**, not opaque data, and `Resources` is the location the one
   community-confirmed report says is copied-but-unsigned. Choosing the executable
   directory keeps the payload in the part of the bundle that is structurally meant to
   hold code.
2. It is the smallest delta against already-shipped, already-hardened code. m10's
   containment checker was fixed against a real attack class (M13, symlinked payload
   root); a layout that keeps its shape keeps that fix exercised instead of re-deriving
   it.

**Consequence for `child_payload_root()`:** under this layout the function's body —
`supervisor_exe.parent().join(CHILD_PAYLOAD_DIR)` (`main.rs:311-315`) — is already
correct for the bundle, because `Contents/MacOS/supervisor`'s parent *is*
`Contents/MacOS`. `resolve_inside()` (`:247-268`) is generic and unchanged either way,
which brief-1 verified against the full call chain.

**This does not make AC4 free, and the implementation must not treat it as free.** Two
things are unverified until a real bundle exists and MUST be proven, not assumed:

- Whether `std::env::current_exe()` inside a launched `.app` resolves to
  `Contents/MacOS/supervisor` under **Gatekeeper path translocation** (a quarantined app
  runs from a randomized read-only mount). The sibling relation is expected to hold
  because the whole bundle is relocated as a unit, but that is an expectation, not a
  measurement.
- Whether the assembly or re-seal step introduces a symlink at the payload root, which
  `resolve_inside()` deliberately refuses.

AC4's re-assertion therefore stays a real test against the real bundle root. "The body did
not have to change" is a fact about the diff, not evidence about the artifact.

## Decision 2a — the payload goes to `Contents/Resources/arxmcp-desktop-child/`

**Accepted 2026-08-12, replacing Decision 2.** The payload tree is placed under
`Contents/Resources/`, which the A/B control proves is sealable.

**This does not re-open R2.** R2 rejected `bundle.resources` — the Tauri *config key*
that copies a tree without signing it. Decision 1 is unchanged: `desktop_package.py`
still pre-signs every nested Mach-O bottom-up before placement, and `codesign --deep`
is still not permitted. What changes is only the destination directory. The
"copies without signing" defect R2 names is a property of the mechanism, not of the
directory, and this ADR does not adopt that mechanism.

The retained argument under Decision 2 — that `Contents/Resources` is where E4's
unsigned-payload failure lives — is answered exactly this way: E4's payloads were
unsigned *because Tauri's resources mechanism placed them*. Ours are signed before they
arrive, by us, and then the outer bundle seals over them.

### Consequence: the payload is no longer a sibling, and TWO layouts must coexist

This is the real cost, and it must not be minimized. Under Decision 2 the bundle
preserved m10's sibling relation and `child_payload_root()` needed no change. Under 2a
it does change, and the supervisor must resolve **two different layouts**:

| context | supervisor at | payload at |
|---|---|---|
| dev / m7 onedir | `<dir>/supervisor` | `<dir>/arxmcp-desktop-child/` (sibling) |
| assembled `.app` | `Contents/MacOS/supervisor` | `Contents/Resources/arxmcp-desktop-child/` |

Both must work: the onedir shape is what every m10 gate and every developer run uses,
and the bundle shape is what ships. The implementation must make this an explicit,
tested disjunction — resolve the bundle-relative location, fall back to the sibling,
and refuse when neither contains a valid payload — never an untested "try one, then the
other" that silently succeeds off the wrong root.

**`resolve_inside()` is unchanged and stays the gate.** Whichever root is selected, the
same canonicalize-then-contain check with the same symlinked-root refusal applies. The
m10 hardening is preserved by construction rather than by re-derivation.

**AC4 must be re-measured against the new location.** The `--print-child-plan` probe
already exists and reports the resolved root and any refusal reason; it is re-pointed,
not re-invented. "The tests passed at the old location" is not evidence about the new
one.

### What this buys and what it does not

Buys: a bundle that seals, which is the precondition for e4 attempting notarization at
all. Does not buy: any claim that it notarizes. Decision 3 is unchanged in full force —
sealing locally and passing Apple's notary are different questions, and E6 is the case
where local `codesign --deep --strict` reported valid and the notary still refused.

## Decision 3 — the notarization question is recorded OPEN, not answered

**Nothing in this repository can settle whether any layout in this ADR survives Apple's
notary service, and this milestone does not claim it does.**

- The evidence establishes that two candidate mechanisms have live failures (E3, E4) and
  that this payload's shape has a recorded notary failure precedent (E6). It establishes
  **nothing positive** about the chosen hybrid. No source confirms that pre-signing plus
  manual placement is sufficient, and none confirms it is insufficient.
- Closing it requires a **build-and-submit trial**: assemble the `.app`, sign it under a
  Developer ID Application certificate, submit via `notarytool`, and read the notary log.
  That certificate is the one `desktop-distribution-spike-4` has never been able to run
  and that epic e4 is blocked on. No further documentation research moves this.
- What would be submitted, so e4 inherits a specification and not a puzzle: the assembled
  `arXMCP.app` containing the bottom-up-pre-signed onedir under
  `Contents/Resources/arxmcp-desktop-child/` (Decision 2a; the sealed layout),
  hardened-runtime enabled, in whichever container
  the size demands; plus, as a cheaper control, a fixture-sized onedir built the same way,
  so a rejection can be attributed to the *mechanism* rather than to scale.

**Binding language rule for every artifact this milestone touches:** no document, string,
comment, commit message or acceptance claim may assert that the artifact is
notarization-ready, Gatekeeper-ready, signable-as-is, or that its signing "works". This
follows m9's treatment of the macOS 14 floor — DECLARED, not exercised — and §4.9's rule
against a bare status token that collapses distinct questions. The distinct questions
here are: (a) does the artifact assemble, (b) does it launch by double-click, (c) is the
payload signed at all, (d) does Apple's notary accept it. m15 can answer (a) and (b);
(c) is answerable only with a certificate; (d) is e4's.

Note for the implementation dispatch: m9's compatibility-claim regression
(`tests/test_desktop_support_floor.py:141-143`) scans root `*.md`, `docs/**`, `apps/**.md`
and `apps/desktop/crates/**/*.rs`. **`.claude/docs/` is outside its scan set**, so this
ADR is not covered by it, and the notarization-claim guard AC2 asks for is new work with
its own scan-scope decision — not a re-point of the macOS-14 patterns.

## Rejected alternatives

**R1 — `bundle.externalBin`.** Rejected on shape *and* on an open bug. Shape: it resolves
one executable per target triple with a `-$TARGET_TRIPLE` suffix (E1); a directory payload
has no documented form, so using it would mean either smuggling the `_internal/` tree in
by a second channel or inventing an unpack-at-first-run convention — self-authored
complexity of exactly the kind m10 already had to justify once. Bug: E3 reports
notarization rejecting the **main app binary**, not the sidecar, merely because
`externalBin` is configured; the issue is open and untriaged against the v2 generation this
repo pins (E7). Additionally, where sidecars land inside `Contents/` is not stated by any
source brief-2 could verify — so adopting it would mean adopting an unverified path as the
anchor of `child_payload_root()`.

**R2 — `bundle.resources`.** Rejected because it copies without signing. E2 confirms the
directory embedding works and is structurally right; E4 confirms — community-confirmed,
not vendor-documented — that dylibs delivered this way are unsigned by the Tauri build and
fail notarization, while the `frameworks` route is signed and passes. There is no
first-class "sign my resources tree" feature. E6 is the same failure class at this
payload's scale: an onedir that failed the notary while `codesign --deep --strict` locally
reported valid. Adopting `resources` would mean adding the same manual pre-signing step
this ADR adopts anyway, *plus* accepting `Contents/Resources` placement and a larger Rust
delta, for no gain.

**R3 — the macOS `frameworks` mechanism.** Rejected as a poor fit, not as broken. It is
the one path E4 shows Tauri signing at build time, and it is genuinely attractive for that
reason. But it is specified for frameworks and individually-named custom dylibs (E5), not
for a several-hundred-file Python closure with its own internal RPATH layout, and
restructuring `_internal/` into framework bundles would rewrite m7's spec and invalidate
its determinism and libomp guards. Recorded as the fallback worth revisiting **if and only
if** a notary trial rejects the hybrid on grounds of unsigned or improperly-sealed nested
code.

**R4 — restructure the payload to PyInstaller `--onefile`.** Rejected. E6 shows onefile
notarizing where onedir did not, so it is a real answer to the risk — but it discards m7's
entire measured surface (per-file determinism manifests, the single-`libomp`
consolidation, the build-root byte scan across `_internal/`), adds first-run extraction
cost to a ~0.75 GB payload, and its extraction directory would sit outside the bundle,
reopening the trust assumption m10's README section exists to bound. Not chosen; recorded
because it is the cheapest escape hatch if notarization proves impossible for multi-file
trees.

**R5 — no Tauri bundler at all** (drive `codesign`/`ditto`/`hdiutil` and hand-build the
`.app` from `desktop_package.py`). Rejected as strictly more work than the hybrid for the
same result: `bundle.macOS.minimumSystemVersion` is consumed at `Info.plist` generation
time by exactly the bundler this would discard, so hand-building means re-implementing
`Info.plist` generation and re-proving m9's floor agreement against a hand-written plist.
The hybrid already avoids both open Tauri bugs without paying that.

## Per-OS consequence of the choice

The portable invariant this ADR commits to is **not** a Tauri config key. Decision 2a
weakened it, and the weaker form is the true one:

> The payload is a directory named `CHILD_PAYLOAD_DIR` at a location the supervisor can
> derive from its OWN on-disk location, in that OS's package format — one enumerated
> candidate per package shape, resolved as an explicit disjunction, never a search.

Under Decision 2 that location was always "beside the supervisor executable". It no
longer is on macOS, which is why the invariant is stated as derivability rather than
adjacency.

- **macOS (`.app`, this milestone's only exercised target):**
  `Contents/Resources/arxmcp-desktop-child/`, derived from
  `Contents/MacOS/supervisor` (Decision 2a). `child_payload_root()` gains the
  two-candidate disjunction; `bundle.active` flips to `true`;
  `minimumSystemVersion: "14.0"` becomes live rather than
  inert. Distribution container (DMG vs zip) is not decided here — see below.
- **Linux (AppImage/deb, portability target, not release-supported):** the invariant is
  satisfiable — an AppImage runs from a mounted image where the payload can sit beside the
  supervisor, and a `.deb` can place both under one `/usr/lib/arxmcp/` directory — but
  neither is built or exercised by this milestone. `make desktop-package` builds on Linux
  today; nothing assembles a Linux package.
- **Windows (NSIS/MSI, portability target):** the invariant is declarable and **not
  exercised, at two removes**. `make desktop-package` cannot run there at all — the build
  lock is macOS-resolved and `--require-hashes` forbids resolving the absent Windows
  dependency (CLAUDE.md §4.5) — and `make desktop-conformance` is already macOS-only
  (issue #423). Windows signing has no analog decided here.

This ADR does **not** claim per-OS parity. It claims that the chosen macOS layout does not
foreclose the other two, which is a weaker and true statement.

## Toolchain onboarding this decision creates

This is the **first invocation of Tauri's bundler in this codebase** (E7). Consequences the
implementation dispatch inherits:

- `tauri-cli` / `cargo-tauri` is not a dependency anywhere in the workspace. Producing an
  `.app` requires adding it (or driving `tauri-bundler`'s lower-level API directly).
- **It must be pinned like everything else it sits beside.** The Tauri crates are pinned
  with `=` and matched in `Cargo.lock` (E7); the PyInstaller build environment is pinned by
  hash (`apps/desktop/pyinstaller/requirements-build.txt`, `--require-hashes`). A
  `cargo install tauri-cli` with no version and no lock would be the only unpinned link in
  a chain that is otherwise pinned end to end. Choosing the pin mechanism — workspace
  dev-dependency vs `cargo install --locked --version` in the gate — is implementation
  work, but "unpinned" is ruled out here.
- It adds a network fetch to the build, on a path that already needs network on first
  provision.
- No committed gate builds the Rust binaries and the frozen child in one session
  (confirmed unchanged since m10's rectify). The combined gate is new authoring, and its
  ~5-minute-plus cost points at a new opt-in marker following the
  `requires_desktop_package` / `requires_bundled_model` precedent rather than folding into
  `make test`.

## What this ADR deliberately does NOT decide

So the implementation dispatch inherits a bounded problem:

1. **The assembly step's mechanism and ordering** — Tauri `beforeBundleCommand` hook vs a
   post-`tauri build` Python step in `desktop_package.py`. Decision 1 fixes the *actor* and
   the *ordering constraint* (pre-sign before the outer seal), not the hook.
2. **What signing identity is used today.** No Developer ID certificate exists. Whether the
   pre-signing step runs ad-hoc (`-`), is skipped with a recorded reason, or is
   certificate-gated is an implementation decision — bounded by Decision 3's language rule.
3. **Distribution container** — `.app` in a zip vs `.dmg`. Only notarization submission
   forces this, and that is e4's.
4. **Assembled-level determinism.** m7's `verify_determinism()` measures the onedir. Whether
   the assembled bundle gets its own manifest comparison, or an argument that onedir
   identity plus deterministic assembly inputs suffices, is open. Docs silence about
   bundler copy behavior is not a reproducibility guarantee.
5. **The PyInstaller executables' own `minos`** (roadmap AC10). Unpinned and unmeasured
   anywhere in the repo; needs `otool -l` against a real build. Surfaced by m15's research,
   arguably m9's gap; not adjudicated here.
6. **The combined gate's name, marker and Makefile target.**
7. **The notarization-claim regression's scan scope** (AC2's guard), including whether
   `.claude/docs/` enters the scanned set.
8. **`apps/desktop/README.md`'s artifact-layout section** (AC7). It must be written from
   the real assembled artifact, not from this decision, so that e4 consumes a measured
   layout rather than an intended one.

## Consequences

- `desktop_package.py` grows from "build the onedir" to "build, sign and place the
  onedir", which makes it the single owner of the payload's whole lifecycle. That is
  concentration, not sprawl, and it keeps m7's guards next to the code that could
  invalidate them.
- m10's containment convention survives m15 rather than being replaced, contrary to what
  `main.rs:307-310` and `apps/desktop/README.md` currently predict. Both prose sites are
  now stale and the implementation dispatch owns correcting them.
- The trust assumption m10 recorded — write access to the payload directory is arbitrary
  code execution as the operator — is **not** closed by bundling. It is narrowed to "write
  access inside the installed `.app`", and only code signing plus install-location
  permissions bound it further. That remains e4's.

## Owner approval record

**Accepted 2026-08-12 by Chris Dare (owner, per OWNERS.md).** Decisions 1, 2 and 3 were
accepted as written, with no amendments, after review of this document in full. The
implementation dispatch that assembles the bundle is unblocked as of that acceptance.

The acceptance covers the decisions only. It does not pre-approve any of the eight items
in "What this ADR deliberately does NOT decide" — those remain the implementation
dispatch's to resolve within the bounds set here, and the two that carry the most risk of
being silently assumed away are called out for the record:

- Decision 2 makes `child_payload_root()`'s body already correct for the bundle. AC4's
  re-assertion is still a real test against a real assembled bundle root — specifically
  including Gatekeeper path translocation and a symlink check at the payload root.
  A diff that changes nothing there is not evidence that nothing needed to change.
- Decision 1's pre-signing step is bottom-up over every nested Mach-O file.
  `codesign --deep` is not a substitute and is not permitted as one.

**Amendment accepted 2026-08-12, same day: Decision 2a replaces Decision 2.** The
implementation dispatch assembled the artifact and measured that `codesign` cannot seal a
bundle whose `Contents/MacOS` holds non-Mach-O files, proving it a property of the
location with an A/B control rather than of this payload. The owner accepted moving the
payload to `Contents/Resources/arxmcp-desktop-child/`.

Worth recording about the process rather than the decision: the implementer did not
relitigate an Accepted ADR. It signed all 180 nested Mach-O files bottom-up, attempted the
seal, recorded the exact failure, pinned `sealed is False` in the gate so a future
toolchain change turns it red rather than silently improving, and escalated. The first
caveat above — that a diff changing nothing is not evidence that nothing needed to change
— is exactly what the measurement disproved, in the opposite direction from the one
expected: the body did not need to change, and the location was wrong anyway.

The amendment's own cost is stated in Decision 2a and is not small: the payload stops
being a sibling of the supervisor, so two layouts must coexist and be tested as an
explicit disjunction.
