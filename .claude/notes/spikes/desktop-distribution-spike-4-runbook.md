# Desktop distribution spike 4 — signing and notarization runbook

**Milestone:** `desktop-distribution-spike-4` / GitHub [#387](https://github.com/chris-dare-dev/arXMCP/issues/387)
**Roadmap question.** Provision or verify the Apple Developer account path and
complete a throwaway `codesign` → hardened runtime → `notarytool` → staple →
Gatekeeper dry run without committing credentials.
**Status:** **BLOCKED — not runnable on this host today.** See § 0.
**Written:** 2026-08-09. Author executed nothing; every command below is for the
owner to run.

---

## 0. Read this before running anything

### 0.1 This host cannot sign for distribution

`security find-identity -v -p codesigning` on this machine (2026-08-09) returns
exactly one identity:

```
  1) D0FFF1712CB1417E2A2924BFC6DD6AAAFA82245E "Apple Development: cedare96@gmail.com (3MFUYKY6T4)"
     1 valid identities found
```

That is an **Apple Development** certificate. It is not a **Developer ID
Application** certificate. They are different certificate types with different
issuing authorities and different purposes:

| | Apple Development | Developer ID Application |
|---|---|---|
| Purpose | Run on your own registered devices | Distribute outside the App Store |
| Requires paid Apple Developer Program | No (free Apple ID works) | **Yes** |
| Accepted by the notary service | No | Yes |
| Gatekeeper verdict on another Mac | Rejected | Accepted once notarized + stapled |
| Typically carries `get-task-allow` | Yes (a notarization rejection) | No |

There is no Developer ID Application certificate in this keychain, so **§§ 3–7
of this runbook cannot be executed today.** Only § 1 is runnable now, and step
1.2 is expected to fail — that failure is the finding, not an error to work
around. Do not read the rest of this document as a procedure that can be run
this afternoon.

The parenthetical `(3MFUYKY6T4)` is part of that certificate's common name as
it already appears on this host. Do not treat it as the Developer ID team
identifier; a paid-program enrollment issues its own team identity, and this
runbook never hard-codes either one — see § 0.3.

### 0.2 Nothing to sign exists yet

`apps/desktop/crates/supervisor/tauri.conf.json` has `"bundle": {"active":
false}`. Nothing in this repository produces an `.app` bundle. `cargo build
--bin supervisor` produces a bare Mach-O executable, not a bundle. § 1.4 lists
what has to land before signing has an input at all.

Spike 1's signing evidence row (`.claude/notes/spikes/desktop-distribution-spike-1.md`)
signed the **PyInstaller `onedir` tree** ad-hoc, not an application bundle, and
that ad-hoc pass proves none of the Developer ID gates — it is release blocker 4
in that ADR, verbatim: "Ad-hoc success proves none of those."

### 0.3 Credential handling — non-negotiable

- No Apple ID, app-specific password, App Store Connect API key, private key
  file, or team identifier is ever written into this repository, any script in
  it, any note under `.claude/`, or any command line that lands in shell
  history.
- Secrets live in exactly one place: a **notarytool keychain profile** in the
  owner's login keychain, created interactively by the owner (§ 1.3).
- Every command below takes secrets by *reference* (`--keychain-profile
  "$NOTARY_PROFILE"`), never by value.
- The shell variables in § 2 are set by the owner in their own interactive
  shell. They are not committed, not exported from a Makefile, and not defaulted
  anywhere in the tree.
- If this ever moves to CI, use an App Store Connect API key (`--key`,
  `--key-id`, `--issuer`) held in the CI secret store plus a dedicated,
  ephemeral keychain — never the login keychain, never an Apple ID password.

---

## 1. Prerequisites

Each prerequisite has a verification command and the output that means "pass".
Run them in order; a failure at step N makes every later step meaningless.

### 1.0 Toolchain (verified present on this host, 2026-08-09)

```bash
xcode-select -p
xcrun --find notarytool && xcrun notarytool --version
xcrun --find stapler
command -v codesign spctl ditto
sw_vers && uname -m
```

Observed on this host — this prerequisite **passes**:

```
/Applications/Xcode.app/Contents/Developer
/Applications/Xcode.app/Contents/Developer/usr/bin/notarytool
1.1.2 (41)
/Applications/Xcode.app/Contents/Developer/usr/bin/stapler
/usr/bin/codesign
/usr/sbin/spctl
ProductName:		macOS
ProductVersion:		26.6
BuildVersion:		25G5028f
arm64
```

`notarytool` ships with Xcode ≥ 13. The Command Line Tools alone are not
sufficient for `notarytool`; if `xcrun --find notarytool` fails, point
`xcode-select` at a full Xcode.

### 1.1 Apple Developer Program enrollment — **NOT SATISFIED**

A paid Apple Developer Program membership (USD 99/year at time of writing) is
the gate for issuing a Developer ID certificate. Enrollment is not instant:
identity verification commonly takes 24–48 hours and can take longer for
organization enrollment (which additionally requires a D-U-N-S number and a
legal-entity check).

**Verification.** There is no offline command for this. The owner checks
enrollment status at <https://developer.apple.com/account>. The proxy signal
this runbook actually depends on is 1.2 — a Developer ID certificate cannot be
issued without an active membership, so a passing 1.2 implies a passing 1.1.

**Expected today:** unknown/absent. This is the first item spike-4 must settle,
and its lead time is the schedule risk for the whole spike.

### 1.2 Developer ID Application certificate installed — **NOT SATISFIED**

Create the certificate via Xcode (Settings → Accounts → Manage Certificates →
`+` → **Developer ID Application**) or via a CSR uploaded at
<https://developer.apple.com/account/resources/certificates>. Xcode's path is
preferred: it generates the private key in the login keychain and never exports
it. The **private key is the irreplaceable asset** — a lost key means revoking
and reissuing; back it up as a password-protected `.p12` stored outside this
repository.

**Verification.**

```bash
security find-identity -v -p codesigning
```

**Pass looks like** — at least one line whose common name begins
`Developer ID Application:`:

```
  1) D0FFF171...245E "Apple Development: cedare96@gmail.com (3MFUYKY6T4)"
  2) <40-hex-SHA1> "Developer ID Application: <Name> (<TEAMID>)"
     2 valid identities found
```

**Actual today:** only line 1 exists. **This prerequisite FAILS.** Everything
from § 3 onward is unrunnable until it passes.

Confirm the chain is complete once it appears — a certificate without its
intermediate is a `errSecInternalComponent` waiting to happen at signing time:

```bash
security find-certificate -c "Developer ID Application" -p login.keychain-db \
  | openssl x509 -noout -subject -issuer -dates
```

Expect `issuer= ... CN=Developer ID Certification Authority` and a `notAfter`
comfortably in the future.

### 1.3 notarytool keychain profile — owner-created, interactive

Run this with **no credential arguments** so nothing enters shell history. The
tool prompts for each field:

```bash
xcrun notarytool store-credentials
```

It asks for a profile name (this runbook assumes `arxmcp-notary`), then either
an App Store Connect API key (key ID, issuer ID, `.p8` path) or an Apple
ID + team ID + app-specific password. App-specific passwords are generated at
<https://appleid.apple.com> under Sign-In and Security; they are not the Apple
ID password. The profile is stored as a generic-password item in the login
keychain under the service `com.apple.gke.notary.tool`.

**Verification — offline, no secret printed:**

```bash
security find-generic-password -s "com.apple.gke.notary.tool" 2>&1 | grep -E '"(acct|svce)"'
```

Pass looks like:

```
    "acct"<blob>="arxmcp-notary"
    "svce"<blob>="com.apple.gke.notary.tool"
```

**Never add `-w` or `-g` to that command** — those flags print the stored
secret. The attribute listing above is sufficient proof the profile exists.

**Verification — online, proves the credential actually authenticates:**

```bash
xcrun notarytool history --keychain-profile "arxmcp-notary"
```

Pass is an HTTP-200 response: either a table of prior submissions or an empty
history. Failure is explicit (`HTTP status code: 401` / `Unable to authenticate`)
and means the profile holds bad credentials, not that the network is down.

### 1.4 A real `.app` bundle to sign — **DOES NOT EXIST**

Signing takes a bundle as input. This repository produces none. Before § 3 has
anything to operate on, a desktop-distribution milestone (not this spike) must
land all of the following:

1. **`bundle.active: true`** in `apps/desktop/crates/supervisor/tauri.conf.json`.
   It is `false` today.
2. **`bundle.macOS.minimumSystemVersion: "14.0"`** — `apps/desktop/README.md`
   names macOS 14 on Apple Silicon as the first release target, and spike 1
   release blocker 3 records that the macOS 26.6 run makes no macOS 14 claim.
   The bundle must declare the floor it claims.
3. **An `.icns` icon.** `crates/supervisor/icons/` contains only `icon.png`;
   macOS bundling wants `.icns`.
4. **The PyInstaller `onedir` payload placed into the bundle** — 759,839,270
   bytes across 5,530 regular files per spike 1, of which 180 are regular Mach-O
   plus 19 symlink aliases. **Where it lands is a signing decision, not a
   packaging detail:** see § 6.1. Mach-O content under `Contents/Resources/` is
   the single most common cause of a bundle that signs but fails
   `--verify --strict`.
5. **Spike 1 release blocker 5 discharged *before* signing** — sanitize
   `arxmcp-0.1.0.dist-info/direct_url.json`, scan every regular file for
   build-root strings, productize the `latex2mathml` data hook. Signing seals
   the tree: any byte changed afterwards invalidates the signature and the
   notarization ticket. Sanitize first, then sign, in that order, always.
6. **A build command.** `apps/desktop/README.md` states the workspace has "no
   Node/npm build chain", so the bundler is the Rust `tauri-cli` crate
   (`cargo install tauri-cli --locked`, then `cargo tauri build`), not
   `npm run tauri`. Pin it like every other dependency in that workspace —
   `apps/desktop/Cargo.toml` pins `tauri = "=2.11.5"` and
   `tauri-build = "=2.6.3"`; an unpinned bundler undoes that discipline.

**Verification, once the above lands:**

```bash
ls -d "$APP" && /usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$APP/Contents/Info.plist"
```

Pass: the directory exists and the printed executable name resolves to an
existing file under `$APP/Contents/MacOS/`.

---

## 2. Shell preamble

Set once per session, in the owner's interactive shell. Nothing here is a
secret; `SIGN_ID` is a public certificate common name, not a credential.

```bash
export APP="/private/tmp/arxmcp-spike4/arXMCP.app"        # build output, never in-tree
export SIGN_ID="Developer ID Application: <Name> (<TEAMID>)"  # exact CN from § 1.2
export NOTARY_PROFILE="arxmcp-notary"                     # § 1.3 profile name
export ZIP="/private/tmp/arxmcp-spike4/arXMCP-submit.zip"
export ENTITLEMENTS=""                                    # empty until § 3.4 proves one is needed
```

Prefer the 40-hex SHA-1 from § 1.2 over the common name if the keychain ever
holds two Developer ID certificates — the string form is ambiguous, the hash is
not.

Work entirely under `/private/tmp/…`. Build output, zips, and notarization logs
must not land in the repository; spike 1 kept its whole 759 MB tree out of the
checkout for exactly this reason.

---

## 3. Signing (inside-out)

### 3.1 Why leaves before containers

`codesign` seals a container by hashing everything inside it, including the
signatures of nested code. Signing a nested binary *after* its container
invalidates the container's seal. So the order is strictly deepest-first, outer
bundle last. Spike 1 recorded this as "Every nested Mach-O ad-hoc signed
inside-out"; the same ordering holds for Developer ID, only the identity and
flags change.

Do **not** sign with `codesign --deep`. Apple documents `--deep` signing as
unsuitable for distribution: it applies one identity and one set of options
uniformly, silently re-signs things you did not intend to, and cannot give
different entitlements to different binaries. `--deep` is fine for
*verification* (§ 4) and wrong for *signing*.

At this tree's scale that means roughly **180 `codesign` invocations plus one
for the bundle**, and the final outer seal hashes all 5,530 regular files.
Budget minutes, not seconds, and expect the sweep to dominate build time.

### 3.2 Clear detritus first

```bash
xattr -cr "$APP"
```

Extended attributes, resource forks, and `.DS_Store`-class metadata make
`codesign` fail with "resource fork, Finder information, or similar detritus not
allowed". Clear before signing, not after.

### 3.3 The inside-out sweep

```bash
# Deepest-first list of every Mach-O file in the bundle.
find "$APP" -type f -print0 \
  | xargs -0 -I{} sh -c 'file -b "{}" | grep -q "^Mach-O" && printf "%s\n" "{}"' \
  | awk -F/ '{print NF"\t"$0}' | sort -rn | cut -f2- > /private/tmp/arxmcp-spike4/macho.txt

wc -l < /private/tmp/arxmcp-spike4/macho.txt   # expect ~180 for the spike-1 tree shape

# Sign leaves.
while IFS= read -r f; do
  codesign --force --timestamp --options runtime \
    ${ENTITLEMENTS:+--entitlements "$ENTITLEMENTS"} \
    --sign "$SIGN_ID" "$f" || { echo "FAILED: $f" >&2; exit 1; }
done < /private/tmp/arxmcp-spike4/macho.txt

# Then any nested bundles (.framework / helper .app), then the outer bundle LAST.
codesign --force --timestamp --options runtime \
  ${ENTITLEMENTS:+--entitlements "$ENTITLEMENTS"} \
  --sign "$SIGN_ID" "$APP"
```

Flag by flag:

- **`--force`** replaces an existing signature. Required here: spike 1's tree is
  already ad-hoc signed, and without `--force` `codesign` refuses with "is
  already signed".
- **`--options runtime`** opts the binary into the **hardened runtime**. This is
  a mandatory notarization precondition, not an optimization. It disables
  DYLD environment-variable injection, blocks unsigned writable-executable
  memory, blocks loading libraries not signed by the same team, and disallows
  process debugging by default — each of which can be selectively re-permitted
  only by an explicit entitlement. Sets `CS_RUNTIME` (`0x10000`) in the
  signature flags.
- **`--timestamp`** requests a **secure timestamp** from Apple's timestamp
  authority. It is a network call, and it is required for notarization: without
  it the signature's validity is tied to the certificate's own lifetime, so the
  app would stop validating when the certificate expires or is revoked. A
  signature made with `--timestamp=none` (or with no `--timestamp`, whose
  default varies by tool version) is rejected by the notary service. **Do not
  sign on an air-gapped machine.**
- **`--entitlements`** — see § 3.4. Left empty by default on purpose.

If `codesign` rejects a file for a malformed identifier — PyInstaller emits
names like `_swigfaiss.abi3.so` — add `--identifier
"com.arxmcp.desktop.$(basename "$f" | tr -c '[:alnum:].' '-')"` for that file.
Keep identifiers stable across builds; they participate in the designated
requirement.

Nested `.framework` bundles are signed at the bundle path (`Foo.framework`),
not at the inner binary, and their versioned directory must be correct before
signing. Helper `.app`s are signed as bundles too, after their own leaves.

### 3.4 Entitlements — where they go and why the default is none

Entitlements are a plist passed per-Mach-O at signing time. If the bundle needs
any, the file belongs at `apps/desktop/crates/supervisor/entitlements.plist`
and is referenced from `bundle.macOS.entitlements` in `tauri.conf.json` for
bundler-driven signing, and via `--entitlements` for the manual sweep above.

**Start with none.** Add an entitlement only when § 4 or § 5 produces a concrete
failure that names it. Each one re-opens a hardened-runtime protection, and the
notary service scrutinizes them.

Candidates a PyInstaller + Torch + FAISS payload plausibly needs, in the order
you would try them:

| Entitlement | Add only when |
|---|---|
| `com.apple.security.cs.disable-library-validation` | A `dlopen` of a nested `.so`/`.dylib` fails at runtime under hardened runtime. Widely needed for Python extension loading. |
| `com.apple.security.cs.allow-jit` | A runtime component genuinely JITs. |
| `com.apple.security.cs.allow-unsigned-executable-memory` | Broader and weaker than `allow-jit`; prefer `allow-jit` first. |
| `com.apple.security.cs.allow-dyld-environment-variables` | Only if the launcher must set `DYLD_*`. Spike 1 forbade `KMP_DUPLICATE_LIB_OK` and never used it — hold the same line here. |

**`com.apple.security.get-task-allow` must NOT be present.** It is the debug
entitlement; Apple Development signing adds it routinely, and it is one of the
standard notarization rejections. This is a concrete way the § 0.1 certificate
difference bites: an Apple-Development-signed binary is *typically already
carrying the entitlement that guarantees rejection.*

---

## 4. Verification after signing

Run all four. Each answers a different question, and none substitutes for
another.

### 4.1 Structural validity

```bash
codesign --verify --deep --strict --verbose=4 "$APP"
```

**Pass:**

```
<path>: valid on disk
<path>: satisfies its Designated Requirement
```

`--deep` here walks nested code (correct for verification, wrong for signing).
`--strict` refuses the lenient legacy rules that let malformed bundles slide.

### 4.2 Signature attributes — the four fields that distinguish this from spike 1

```bash
codesign -dv --verbose=4 "$APP" 2>&1
```

**Pass** requires all four:

| Field | Required value | Spike 1's ad-hoc result |
|---|---|---|
| `Authority=` | `Developer ID Application: <Name> (<TEAMID>)`, then `Developer ID Certification Authority`, then `Apple Root CA` | absent — `Signature=adhoc` |
| `TeamIdentifier=` | the team ID | **`not set`** (recorded verbatim in the ADR) |
| `flags=` | contains `runtime` (e.g. `0x10000(runtime)`) | **`0x2(adhoc)`** — explicitly `adhoc` |
| `Timestamp=` | a real date from Apple's TSA | absent |

This table *is* the delta spike 1 could not close. Spike 1 passed
`codesign --verify --deep --strict` while every one of these four fields was
wrong — which is precisely why "ad-hoc success proves none of those" is release
blocker 4 and not a footnote. **A green § 4.1 with a red § 4.2 is exactly the
spike-1 result.** Do not report § 4.1 alone as a signing pass.

### 4.3 Sweep every nested binary, not just the outer bundle

The outer seal being valid does not prove each of the 180 nested Mach-O files
got `runtime` and a timestamp — a leaf signed without `--options runtime` can
still sit inside a valid container and will be caught only by the notary
service, minutes into an upload.

```bash
fail=0
while IFS= read -r f; do
  out=$(codesign -dv --verbose=4 "$f" 2>&1)
  printf '%s' "$out" | grep -q 'flags=.*runtime'                   || { echo "NO RUNTIME: $f"; fail=1; }
  printf '%s' "$out" | grep -q 'Authority=Developer ID Application' || { echo "NOT DEVID:  $f"; fail=1; }
  printf '%s' "$out" | grep -q '^Timestamp='                        || { echo "NO TS:      $f"; fail=1; }
  printf '%s' "$out" | grep -q 'adhoc'                              && { echo "ADHOC:      $f"; fail=1; }
done < /private/tmp/arxmcp-spike4/macho.txt
echo "sweep fail=$fail"   # pass: fail=0 and no lines above it
```

`grep -q` on an empty capture returns non-zero, so a `codesign` invocation that
produced nothing fails loudly rather than passing silently. Assert the input
list is non-empty (`wc -l`, § 3.3) before trusting a clean sweep — an empty loop
also prints `fail=0`.

### 4.4 Entitlements actually attached

```bash
codesign -d --entitlements - "$APP/Contents/MacOS/$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$APP/Contents/Info.plist")"
```

**Pass:** either no entitlements (the § 3.4 default) or exactly the plist you
intended. **`com.apple.security.get-task-allow` present is a hard fail** —
re-sign without it before submitting; do not spend a notarization round trip
proving what this command already told you.

---

## 5. Notarization

### 5.1 Package for submission

The notary service accepts `.zip`, `.dmg`, or `.pkg` — not a bare `.app`.

```bash
ditto -c -k --keepParent "$APP" "$ZIP"
ls -l "$ZIP"
```

**Use `ditto`, not `zip`.** Spike 1 measured 19 symlinks carrying 605 bytes of
link payload in this tree; `ditto` preserves symlinks, extended attributes, and
resource metadata, and `--keepParent` keeps the `.app` directory itself inside
the archive. A `zip`-created archive that dereferences or mangles symlinks
produces a payload the notary service evaluates as a *different, broken* tree.

Expected size, from spike 1's numbers: the payload zipped to 262,826,333 bytes
there, so budget roughly a quarter-gigabyte upload plus the Tauri shell.

### 5.2 Submit and wait

```bash
xcrun notarytool submit "$ZIP" \
  --keychain-profile "$NOTARY_PROFILE" \
  --wait --timeout 2h
```

**Pass:**

```
  id: <uuid>
  status: Accepted
```

`--wait` blocks until the service reaches a terminal state. Without it you get
only a submission ID and must poll `xcrun notarytool info <id>`. Record the
submission ID either way — it is the only handle on the log.

Typical turnaround is minutes; a quarter-gigabyte upload plus queueing can push
it longer, hence the explicit `--timeout`.

### 5.3 On rejection, read the log — the status is not the diagnostic

`status: Invalid` tells you nothing actionable. The log is the diagnostic:

```bash
xcrun notarytool log <submission-id> \
  --keychain-profile "$NOTARY_PROFILE" \
  /private/tmp/arxmcp-spike4/notarization-log.json

python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("statusSummary")); [print(i["severity"], i["path"], i["message"]) for i in d.get("issues") or []]' \
  /private/tmp/arxmcp-spike4/notarization-log.json
```

Each entry names a `path` inside the archive and a `message`. With 180 Mach-O
files, the log will typically name a *specific* one — that path is where you
re-sign. `issues: null` with `status: Invalid` means the archive itself was
unreadable (§ 6, "wrong archive tool").

Never report a notarization failure without its log entries attached. A bare
status is not evidence.

### 5.4 Staple, then validate

```bash
xcrun stapler staple "$APP"
xcrun stapler validate -v "$APP"
```

**Pass:** `The staple and validate action worked!`

Stapling attaches the notarization ticket to the bundle so Gatekeeper can
validate **offline**. Without it, a first launch on a machine with no network
(or with the notary service unreachable) has no ticket to check.

Two ordering facts:

- **You staple the `.app`, not the submitted `.zip`.** Zip archives cannot be
  stapled. The archive from § 5.1 is a submission vehicle only.
- **Re-package after stapling.** The zip you uploaded contains an unstapled
  bundle. Distribute a *new* archive created from the stapled `.app`.

Then confirm stapling did not disturb the seal:

```bash
codesign --verify --deep --strict --verbose=4 "$APP"
codesign --test-requirement="=notarized" --verify --verbose "$APP"
```

Pass: `valid on disk` again, and the requirement test reports the bundle
satisfies `notarized`. The second command is the cheapest local proof that the
ticket is really attached and really matches this signature.

---

## 6. Gatekeeper verification on a clean machine

### 6.1 The assessment

```bash
spctl -a -vvv -t install "$APP"
```

**Pass:**

```
<path>: accepted
source=Notarized Developer ID
origin=Developer ID Application: <Name> (<TEAMID>)
```

`source=Notarized Developer ID` is the line that matters. `source=Unnotarized
Developer ID` means signing worked and notarization or stapling did not.

Note on `-t`: `-t install` is the assessment type for installers and disk
images, and `-t exec` is the type for an executable bundle. Run both on an
`.app`; they exercise different policy paths and a distribution that ships a
`.dmg` needs the `install` verdict on the disk image as well:

```bash
spctl -a -vvv -t exec "$APP"
spctl -a -vvv -t install "$DMG"    # if the release ships a .dmg
```

If the release ships a `.dmg`, the disk image is itself signed, notarized, and
stapled after the `.app` inside it is — the inner staple does not cover the
outer container.

### 6.2 Why the build host is the weak claim

Verifying on the machine that built and signed the app is close to
self-certification. That host:

- **holds the signing private key**, so it trusts the leaf certificate for
  reasons no other Mac shares;
- **produced the files locally**, so they carry no `com.apple.quarantine`
  extended attribute — and Gatekeeper's full assessment only engages on
  quarantined files. A locally built app opens because it was never quarantined,
  not because it would pass;
- **may have developer-mode assessment state**, cached assessments, or a
  disabled assessment policy from earlier work;
- **has every build dependency present**, so a missing bundled library shows up
  as a working app here and a crash-on-launch elsewhere. Spike 1's runtime guard
  proved `sys.executable` and `sys.path` stayed inside the bundle *on this
  host* — a different machine is what turns that into a portability claim.

A clean machine that never saw the source removes all four confounders at once.
The real test, in order of strength:

1. **Strongest.** Transfer the stapled archive to a Mac that has never held the
   signing certificate or the source tree, download it over the network (so the
   OS applies quarantine), double-click, and confirm it opens with no
   "unidentified developer" or "malware" dialog. Then disconnect the network and
   relaunch — that is what stapling buys.
2. **Weaker but useful on the build host**: simulate quarantine on a *copy*
   before assessing.

   ```bash
   cp -R "$APP" /private/tmp/arxmcp-spike4/quarantined.app
   xattr -w com.apple.quarantine "0081;00000000;spike4;" /private/tmp/arxmcp-spike4/quarantined.app
   spctl -a -vvv -t exec /private/tmp/arxmcp-spike4/quarantined.app
   ```

3. **Weakest.** `spctl` on the freshly built, unquarantined bundle. Report it as
   a smoke check, never as the Gatekeeper claim.

Spike 1's support-floor gap compounds this: that run was macOS 26.6 arm64 and
made no macOS 14 claim (release blocker 3). The clean machine should be on the
**oldest supported macOS** — macOS 14, per `apps/desktop/README.md` — or the
spike closes the Developer ID gate while leaving the support-floor gate exactly
as open as spike 1 left it.

---

## 7. Failure modes and their diagnostics

| Failure | Diagnostic | Remedy |
|---|---|---|
| **Unsigned nested binary** | § 4.1 `code object is not signed at all In subcomponent: <path>`; or notary log `The binary is not signed.` naming the path | Add that path to the § 3.3 list and re-run the sweep leaves-first. Detect it before submitting — the § 4.3 sweep is what catches it in seconds instead of after a 260 MB upload. |
| **Mach-O under `Contents/Resources/`** | § 4.1 `bundle format unrecognized, invalid, or unsuitable`, or an unsigned-code complaint at a `Resources/` path even though you signed it | `Contents/Resources` is sealed as *data*. Relocate executable payload to `Contents/Frameworks/` (Tauri `bundle.macOS.frameworks`) or `Contents/MacOS/`; keep only non-code data in Resources. This is the § 1.4(4) decision — settle it before signing, not after. |
| **Missing hardened runtime** | § 4.2/4.3 `flags=0x0(none)` — no `runtime`; notary log `The executable does not have the hardened runtime enabled.` | Re-sign that binary with `--options runtime`. Usually a leaf missed by the sweep, or a container signed before a leaf and not re-signed. |
| **Missing secure timestamp** | § 4.2/4.3 has no `Timestamp=` line (or shows `Signed Time=`, which is the *local* clock, not a TSA timestamp); notary log `The signature does not include a secure timestamp.` | Re-sign with `--timestamp` **on a networked machine**. Apple's TSA is a live service; a silent failure here usually means the signing host had no route to it. |
| **`get-task-allow` present** | § 4.4 shows `com.apple.security.get-task-allow`; notary log `The executable requests the com.apple.security.get-task-allow entitlement.` | Remove it from the entitlements plist and re-sign. If it appeared without you adding it, you signed with an **Apple Development** identity (§ 0.1), not Developer ID. |
| **Disallowed / over-broad entitlement** | Notary log names the entitlement and the path | Drop it and re-test; if the runtime genuinely needs it, prefer the narrowest form (`allow-jit` over `allow-unsigned-executable-memory`). Never widen entitlements to make an unexplained failure go away. |
| **Unsigned library / `dlopen` failure at runtime** | App launches then dies; Console shows `code signature ... not valid for use in process` | Either the library was missed by the sweep (fix the sweep) or hardened-runtime library validation is blocking a legitimately different-team library (add `disable-library-validation` — deliberately, with a note saying why). |
| **Stapling a not-yet-approved submission** | `xcrun stapler staple` → `CloudKit query for ... failed due to "Record not found"` or `Error 65` | The ticket does not exist yet. `xcrun notarytool info <id>` — if `status` is `In Progress`, wait; if `Invalid`, § 5.3. **Stapling is not the step that grants approval**; it only fetches an approval that already exists. |
| **Wrong archive tool** | Notary `status: Invalid` with `issues: null`, or "The archive could not be extracted" | Re-create with `ditto -c -k --keepParent` (§ 5.1). |
| **Any post-signing modification** | `codesign --verify` flips to `a sealed resource is missing or invalid` on a bundle that verified minutes earlier | Something touched the tree after signing — a sanitization pass, a log write, a `.DS_Store`. Restart from § 3 on a clean build; never patch a signed bundle. |
| **Ticket revoked / cert expired later** | Previously-fine app starts failing Gatekeeper on user machines | The secure timestamp is what keeps already-signed builds valid past certificate expiry. If § 4.2 showed no `Timestamp=`, this is the bill arriving. |

---

## 8. What this proves — and what it does not

### Proves

Completing §§ 3–6 with the stated expected outputs establishes **distribution
trust**: macOS on a machine that has never seen this source tree will accept the
application as coming from an identified Apple developer, unmodified since
signing, scanned by Apple's notary service, and validatable offline.

That is genuinely the thing spike 1 could not claim. Spike 1's ad-hoc signature
passed `codesign --verify --deep --strict` with `flags=0x2(adhoc)` and
`TeamIdentifier` unset — a self-consistent seal that no other Mac has any reason
to trust.

### Does not prove

**Distribution trust is not correctness.** Notarization's automated scan checks
for signing conformance and known malware. It does not run the application, does
not evaluate whether it works, and is not a code review.

Specifically, the other four spike-1 release blockers are **independent** and
remain exactly as open after a green run of this runbook:

1. **The installed-wheel FAISS/Torch OpenMP collision** (blocker 1). The frozen
   probe passed only because FAISS's `LC_RPATH @loader_path/..` resolved
   `_internal/libomp.dylib` rather than its redundant nested copy. Signing seals
   whichever libraries are present; it does not make the consolidation
   intentional or regression-tested. A notarized app can still abort with
   OpenMP Error #15 on first search.
2. **Real BGE-M3 exercise** (blocker 2). Spike 1 proved loader and extension
   closure against a tiny XLM-R model with output shape `[1,3,8]` — not BGE-M3
   weights, not retrieval quality, not first-run download. No model belongs in
   the bundle, so no amount of bundle signing touches this.
3. **macOS 14 support floor** (blocker 3). Signing on macOS 26.6 makes no
   compatibility claim about macOS 14. § 6.2 is where this spike can *partly*
   help, by choosing the clean machine deliberately — but only for Gatekeeper
   acceptance, not for whether the app runs there.
4. **Productization of the `latex2mathml` hook, `freeze_support()` behavior,
   `direct_url.json` sanitization, and build-root string scanning** (blocker 5).
   These must all complete **before** signing (§ 1.4(5)); signing a tree does
   not clean it, it freezes it.

Also not proved: descendant-process cleanup on the forced shutdown rung, which
`apps/desktop/README.md` records as an explicit open item for a future
desktop-distribution milestone; and the wildcard-bind arms, which that same
README records as not ported.

### What a successful spike-4 actually returns

A GO/NO-GO on the roadmap's `[MUST]`: *are signing and notarization credentials
available to this project?* Today the honest answer, from § 1.2, is **no** — one
Apple Development identity, zero Developer ID Application identities, no
evidence of paid-program enrollment, and no `.app` bundle to sign. The
throwaway dry run the ticket asks for cannot start until § 1.1 and § 1.2 pass,
and § 1.1's lead time is measured in days.
