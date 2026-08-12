---
milestone_id: "desktop-distribution-m15"
researcher_role: "general"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://v2.tauri.app/develop/sidecar/"
    sha256: "bbc36e085c552d4e520f049ef6f88374c7e26fc8d3895d963149ce7cfc1b09b0"
    takeaway: "externalBin expects one executable file per platform (name-$TARGET_TRIPLE suffix), not a directory payload; macOS bundle placement of the sidecar is not documented on this page."
  - url: "https://v2.tauri.app/develop/resources/"
    sha256: "6f2c5e15827e4da507c975cb92de4a5c2be3b1aba99620b21f3f8c4df40ddf0e"
    takeaway: "bundle.resources DOES support whole-directory embedding (trailing slash or glob) into $RESOURCE, preserving structure; exact macOS Contents/ subpath is not stated on this page."
  - url: "https://github.com/tauri-apps/tauri/issues/11992"
    sha256: "432b6142a4581a8a1845476aa20c09b415631f14a5e30f500cab37ac4c168f87"
    takeaway: "open, untriaged bug (Tauri v2): notarization rejects the MAIN app binary with an invalid-signature error specifically WHEN externalBin sidecars are present; removing externalBin fixes it. No official fix as of fetch."
  - url: "https://github.com/orgs/tauri-apps/discussions/12001"
    sha256: "9c7e13e5b28ee19beee93e527d89566e9e3506d1bd320543edd06ec7bbee40a4"
    takeaway: "community-confirmed: dylibs shipped via bundle.resources are NOT signed by the Tauri build and fail notarization; dylibs shipped via macOS 'frameworks' config ARE signed at build time and notarize successfully. No first-class 'sign my resources tree' feature exists."
  - url: "https://raw.githubusercontent.com/tauri-apps/tauri-docs/v2/src/content/docs/distribute/macos-application-bundle.mdx"
    sha256: "eebeb6d052990159229027e336ffcb3c0d92fdba480431af71dd392f1bad7def"
    takeaway: "canonical Tauri macOS bundle layout: Contents/{MacOS,Resources,Frameworks,PlugIns,SharedSupport,_CodeSignature}; custom dylibs/frameworks need explicit config and are placed/signed via the frameworks mechanism, not generic resources."
  - url: "https://github.com/pyinstaller/pyinstaller/issues/8927"
    sha256: "01f027dc18b7b55337980a1c14f24384f9bd5090713161546846f7a21bc0a582"
    takeaway: "real-world precedent: a PyInstaller --onedir app (many nested .dylib/.so across Contents/Resources and Contents/Frameworks) notarizes fine with --onefile but fails notarization with --onedir even when local `codesign --deep --strict` reports valid — Apple's notary service is stricter than local verification for multi-file trees."
injection_attempts: 0
---

# Research brief (general) — desktop-distribution-m15

## Pinned repo facts (read directly, not web-sourced)

- Tauri crate pins (`apps/desktop/Cargo.lock`, confirmed 2026-08-11):
  `tauri = 2.11.5`, `tauri-build = 2.6.3`, `tauri-utils = 2.9.3`. Workspace
  `Cargo.toml` pins these with `=` (exact), so "Tauri v2" research below is
  scoped to the v2.11.x bundler generation, not v1 or a future v2 minor.
- `apps/desktop/crates/supervisor/tauri.conf.json` today: `"bundle": {"active":
  false, "icon": [...], "macOS": {"minimumSystemVersion": "14.0"}}` — no
  `resources`, no `externalBin`, confirmed independently of m10's finding.
- The payload in question is m7's PyInstaller **onedir** output — hundreds of
  `.so`/`.dylib` files plus a top-level executable, not a single sidecar
  binary, per `apps/desktop/README.md`'s own framing of what m15 must embed.

## External sources

See frontmatter `sources:`. Three source classes: (1) Tauri's own v2 docs for
the two candidate mechanisms, (2) two independent bug/discussion threads
showing the failure modes that hit exactly this multi-file-nested-code shape
in production, (3) a PyInstaller-specific precedent for `--onedir` (not
`--onefile`) notarization, which is the same shape as m7's output.

## Question 1 — `bundle.resources` vs `bundle.externalBin` vs sibling-directory convention, for a ~0.75 GB multi-file onedir

**`externalBin` is structurally the wrong mechanism for this payload.**
Tauri's own docs describe it as one binary per platform: "a binary with the
same name and a `-$TARGET_TRIPLE` suffix must exist" — the whole feature is
built around resolving exactly one file per target triple at build time and
invoking it as a `Command::sidecar()` child process. There is no documented
directory form. To use `externalBin` for an onedir you would have to either
(a) point it at the onedir's own launcher executable and separately smuggle
the hundreds of supporting `.so`/`.dylib` files in through some other
channel, defeating the point of using one mechanism, or (b) invent an
unsupported convention (e.g. zip-and-unpack at first run), which is out of
scope for "assemble a bundle" and reintroduces exactly the kind of
self-authored complexity m10 already had to justify for the launch plan.
**Conclusion: `externalBin` does not fit a multi-file onedir; it fits a
single already-linked launcher binary, if the onedir is later restructured
around one.** This is the one part of Question 1 the docs answer
unambiguously.

**`bundle.resources` DOES support directory embedding.** The v2 resources
page states directories can be included with a trailing slash or a glob, and
that "the entire directory will be copied to the `$RESOURCE` directory,
preserving the original structures." This is structurally the right shape
for an onedir tree: point `resources` at the onedir root (or a glob under
it) and it lands, structure intact, under `<App>.app/Contents/Resources/`.

**Where each mechanism lands inside `Contents/` — ambiguous in the primary
docs, resolved only by secondary sources.** Neither the sidecar page nor the
resources page states the exact `Contents/` subpath. The canonical bundle
structure doc (macos-application-bundle.mdx) names `Contents/MacOS` (the main
executable only), `Contents/Resources` (icons + "other resources" +
resources-config output), `Contents/Frameworks` (frameworks/dylibs configured
via the separate `frameworks` key, not `resources`), `Contents/PlugIns`, and
`Contents/SharedSupport`. Community reports (discussion #12001) corroborate
that `resources`-configured content lands under `Contents/Resources`. Where
`externalBin` sidecars land is **not stated in any source I could verify** —
issue #11992's repro places the sidecar and shows failure but does not spell
out the exact path; general Tauri community knowledge (not independently
verified here, flagged as unverified) is that sidecars land alongside the
main binary under `Contents/MacOS`. **Record this as unresolved rather than
assumed** — the ADR should either verify it by inspecting a built `.app`
locally (cheap, no web dependency) or treat it as a known gap.

**Sibling-directory convention off `current_exe()`** — this is exactly what
m10 already implemented for the pre-bundle onedir (per
`apps/desktop/README.md`'s "Child payload layout" section:
`<supervisor dir>/arxmcp-desktop-child/arxmcp-desktop-child`, resolved via
canonicalize + component-wise containment, root refused if a symlink). Inside
a `.app`, "sibling of the supervisor executable" means literally
`Contents/MacOS/arxmcp-desktop-child/`. This is NOT a Tauri-native mechanism
— it requires `desktop_package.py` (m7) or a bundler build step to copy the
onedir tree into that location manually (e.g. via a Tauri `beforeBundleCommand`
hook or a resources-config entry targeted at `Contents/MacOS/` rather than
`Contents/Resources/`), and the *existing* containment check
(`resolve_inside`, `child_payload_root`) already assumes exactly this
sibling-of-executable shape. **This is the option requiring the least change
to already-shipped, already-fixed-for-symlink-attack code (m10's rectify
fixed the exact "symlinked root" attack class in this checker).**

## Question 2 — codesigning implications

Two independent, corroborating findings say the same thing from different
angles:

1. **Issue #11992** (open, untriaged, no fix): using `externalBin` at all
   causes Tauri v2's own MAIN app binary notarization to fail with an
   invalid-signature error on macOS — a regression that has nothing to do
   with the sidecar's own contents, just its presence. This is a live,
   unresolved bug in the exact mechanism dismissed in Q1 as structurally
   unsuited to this payload anyway; it independently reinforces avoiding
   `externalBin` here.
2. **Discussion #12001**: dylibs placed via `bundle.resources` are **not
   signed by the Tauri build** and fail notarization as-is; the only
   confirmed working path for embedding signed dylib content is the
   `frameworks` mechanism (system frameworks by name, custom
   frameworks/dylibs by explicit path), which the bundler signs at build
   time. Generic `resources` content is copied but not code-signed.

Apple's own signing model (general knowledge, not independently re-verified
via a fetched primary source this session — flagged) requires nested
executable code to be signed "bottom up" and does not recursively sign or
notarize content dropped into `Resources`; `codesign --deep` is explicitly
discouraged for this in community guides because it does not reliably
reach every nested Mach-O. A PyInstaller onedir's `.so`/`.dylib` files ARE
Mach-O executable code (not opaque data), so if they land under
`Contents/Resources` via the naive `bundle.resources` glob, they are
copied but never signed by Tauri's build, and Gatekeeper/notarization will
reject the unsealed executables inside — this is exactly the failure class
discussion #12001 hit with a handful of dylibs, and PyInstaller issue #8927
shows the same failure class at onedir scale (hundreds of files): a build
that notarizes fine with `--onefile` (single signed Mach-O) fails with
`--onedir`, with the notary service flagging "invalid signature" on multiple
nested binaries even when local `codesign --deep --strict` reported them
valid.

**Working conclusion (not settled — flagged as the ADR's real decision):**
neither `bundle.resources` (copies but does not sign) nor `bundle.externalBin`
(wrong shape, plus an open corruption bug for the main binary) is a
turnkey signed path for this payload. The two threads point toward: the onedir
tree must be individually codesigned bottom-up (every nested Mach-O file, not
just the top-level launcher) as a **separate step outside Tauri's bundler**
— likely inside `desktop_package.py`/`arxmcp_desktop.spec` (m7) before the
Tauri build even runs, or as a `beforeBundleCommand`/post-bundle hook — with
Tauri's bundler then only responsible for copying the pre-signed tree into
place and doing its own outer-bundle signature over the whole `.app`. This
mirrors the one mechanism in the docs that IS confirmed to work
(`frameworks`, which Tauri signs at build time) by doing manually for
`resources` content what `frameworks` gets for free. e4 (blocked on the
Developer ID cert) is the actual consumer of this decision and should be
consulted before the ADR treats it as closed, since m15 cannot itself
exercise real signing without that cert.

## Question 3 — does m7's determinism survive assembly

Not independently verifiable from external sources — this is an internal
question about `apps/desktop/pyinstaller/desktop_package.py` and
`arxmcp_desktop.spec`'s reproducibility guarantees (build-root string
scrubbing, `direct_url.json` sanitization) crossed with Tauri's bundler
behavior. What I can say from the fetched sources: the `resources` config
copies files "preserving the original structures" (no stated reordering),
and Tauri's own signing step (for platforms it actually signs) runs LAST,
producing separate `.sig` files rather than mutating the copied resource
tree in place — nothing in the fetched docs describes the bundler rewriting,
re-timestamping, or reordering copied resource bytes. However, this is
silent-by-omission, not a positive guarantee: none of the fetched sources
make an explicit reproducibility claim about `bundle.resources` copy
behavior, macOS `_CodeSignature` generation, or `Info.plist` byte layout
across repeated builds. **Record as open**: m15 needs its own before/after
hash comparison of the onedir tree pre- and post-bundling (extending m7's
existing determinism gate to run across `make desktop-package`, per this
milestone's own acceptance criteria) rather than trusting docs silence as a
guarantee.

## Question 4 — practical limits from the ~0.75 GB payload

- **Notarization upload/format**: any single file over 4 GiB inside the
  submission requires switching from a plain zip to a disk image (DMG) or
  compatible container, because notarytool's servers cannot parse the ZIP64
  format that a >4 GiB zip requires. A 0.75 GB onedir is well under this
  per-file threshold for any individual `.so`/`.dylib`, but the AGGREGATE
  submission size matters for upload time, not correctness: real-world
  reports cite 40–60 minutes for a 2.8 GB DMG upload+status cycle, and
  3.5–4.5 hour full notarization runs for "large" macOS apps at unspecified
  size — so a 0.75 GB bundle should notarize (once codesigning is solved)
  but should be expected to take materially longer than a trivial app,
  which matters for e4's CI/gate design even though e4 itself is blocked.
- **DMG/zip packaging step**: no size ceiling found in any fetched source
  for DMG creation itself at 0.75 GB; this is two to three orders of
  magnitude below what's been reported working (up to ~100 GB compressed
  submissions cited by forum posts). Not a blocker.
- **Bundle size**: no Tauri-specific ceiling found; Tauri's bundler is a
  file-copy operation, not a size-constrained format, for both `resources`
  and DMG output.

**No hard limit found that blocks 0.75 GB.** The practical cost is
notarization wall-clock time and, per Question 2, whether the payload can be
correctly signed at all — that is the real gating question, not size.

## Conflicts and what would resolve them

1. **Exact `Contents/` subpath for `externalBin` sidecars** — not stated in
   Tauri's own docs; secondary/community claims (unverified this session)
   say `Contents/MacOS`. Resolve by inspecting a locally built `.app` with a
   trivial `externalBin` entry, or by filing/finding a Tauri issue that
   states it explicitly. Low priority since Q1 already rules `externalBin`
   out on shape grounds alone.
2. **Whether `bundle.resources` content can be made to pass notarization at
   all without a pre-signing step** — discussion #12001's dylib case is
   small-scale (a handful of files) and its author calls their `frameworks`
   workaround a workaround, not a documented supported path for arbitrary
   Python `.so` trees. No source confirms `resources` + manual pre-signing
   is sufficient and none confirms it is not; PyInstaller issue #8927 shows
   a case where careful local signing still failed notary-side. **This is
   the single biggest open risk for the ADR** and should be resolved by a
   throwaway build-and-submit spike against a fixture-sized onedir before
   the ADR treats "pre-sign then copy via resources" as settled, not by
   documentation research alone — no further web research will resolve it,
   only an empirical trial (which m15 cannot run today without e4's cert).
3. **Reproducibility of the bundler's copy step** (Question 3) — resolved by
   an internal hash-comparison gate, not by external research.

## Risk and alternative

**Riskiest assumption in the brief:** that a bundle-mechanism ADR can be
written as a clean choice among three options when the evidence says two of
the three (`externalBin` for this shape, `resources` for signed executable
content) are actively broken or unconfirmed for a payload this large and
multi-file, and the third (sibling-directory convention) is the one m10 has
already built and hardened but is not a Tauri-native mechanism at all — it
requires custom build-script glue to place the onedir inside
`Contents/MacOS/` and custom pre-signing before the Tauri build touches it.
The ADR's "chosen mechanism" is likely to be a hybrid — sibling-directory
placement via a build hook, individually pre-signed bottom-up — rather than
a single stock Tauri config key, and the ADR should say so explicitly rather
than force-fitting the roadmap's three named options into a false choice.

**Concrete alternative:** skip Tauri's bundler for the child payload entirely
and drive `codesign`/`ditto`/`pkgbuild`/`hdiutil` directly from
`desktop_package.py` (m7's existing owner of the onedir), building the
`.app` shell with Tauri as today (window/binary only, `bundle.active: true`
with no `resources`/`externalBin` at all) and then a post-Tauri-build script
step that copies the pre-signed onedir into `Contents/MacOS/` and re-seals
the outer bundle. This sidesteps both open Tauri bugs (Q1/Q2) at the cost of
a bespoke assembly script the ADR would need to own and document instead of
delegating to Tauri config — worth naming as the alternative because it is
the only path in this research with no unresolved-mechanism risk, only
implementation cost.
