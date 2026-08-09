# Investigation — what can honestly be claimed about the macOS 14 support floor, from a macOS 26.6 host

**Status:** Investigation only. No code, roadmap, or README file was modified.
**Date:** 2026-08-09
**Relates to:** `desktop-distribution-spike-1` release blocker 3; roadmap `[SHOULD]` assumption
"macOS 14+ on Apple Silicon is an acceptable initial support floor".

## Host under measurement

| Fact | Value |
|---|---|
| OS | macOS 26.6, build `25G5028f` (`sw_vers`) |
| Kernel | `Darwin 25.6.0 … RELEASE_ARM64_T6041` |
| Hardware | MacBook Pro `Mac16,5`, Apple M4 Max, arm64 |
| Repo HEAD | `dd2b499` |
| Rust | `rustc 1.93.0`, LLVM 21.1.8, host `aarch64-apple-darwin` |
| Xcode SDK | 26.5 (`xcrun --show-sdk-version`) |
| Oldest SDK present anywhere on disk | **15.2** — `find / -name 'MacOSX14*.sdk'` returned nothing |

Everything below was measured on this host on this date. Where a statement is inference rather than
measurement it is marked **(inferred)**.

---

## Bottom line — the single strongest honest statement

> On a macOS 26.6 arm64 host, every Mach-O image in the desktop closure declares a macOS deployment
> target of 14.0 or lower, imports no dynamic symbol absent from the macOS **15.2** SDK stubs, and the
> Rust supervisor and fixture sidecar build, load, and pass the full 42-test desktop contract gate with
> zero skips when their deployment target is pinned to 14.0. **No part of the bundle has been executed
> on macOS 14, no macOS 14 SDK exists on this host to check symbol availability against, and this host
> is hardware-incapable of running macOS 14 — so nothing here is a macOS 14 compatibility claim.**

Read the two halves together. The first half says nothing was found that *contradicts* a macOS 14
floor. The second half says the observation that would *support* one has not been made. "Nothing
contradicts it" is not "it works", and the wording above is deliberately shaped so it cannot be
quoted as the latter.

---

## Claim → obtainable here / requires macOS 14 → evidence

| # | Claim | Obtainable here? | Evidence or reason |
|---|---|---|---|
| 1 | The supervisor and fixture sidecar declare minOS 11.0 / SDK 26.5, arm64-only | **Yes — measured** | `otool -l apps/desktop/target/debug/{supervisor,fixture-sidecar}` → `LC_BUILD_VERSION platform 1, minos 11.0, sdk 26.5`; `lipo -archs` → `arm64` |
| 2 | The highest declared minOS anywhere in the Python closure is 14.0 | **Yes — measured** | 200 Mach-O files under `.venv`, all carrying `LC_BUILD_VERSION`: 31 × 11.0, 37 × 12.0, **132 × 14.0**. The 14.0 set is scipy (111), numpy (19), faiss (2) |
| 3 | 14.0 is a *hard* inherited floor, not a preference | **Yes — measured** | `faiss_cpu 1.13.2` publishes exactly one arm64 macOS wheel in `uv.lock`: `faiss_cpu-1.13.2-cp310-abi3-macosx_14_0_arm64.whl`. There is no lower-tagged arm64 build to fall back to |
| 4 | numpy/scipy at 14.0 is a *resolver choice*, not a hard floor | **Yes — measured** | `uv.lock` carries both `numpy-2.4.4-cp312-cp312-macosx_11_0_arm64.whl` and `…macosx_14_0_arm64.whl` (scipy: `12_0` and `14_0`). Installed `dist-info/WHEEL` shows `Tag: cp312-cp312-macosx_14_0_arm64` for both — the highest tag this host accepts |
| 5 | The supervisor's minOS can be pinned to 14.0 | **Yes — proven by rebuild** | `MACOSX_DEPLOYMENT_TARGET=14.0 cargo build --locked … --bin supervisor --bin fixture-sidecar` finished in 25.08 s, exit 0; both binaries then report `minos 14.0, sdk 26.5` |
| 6 | Pinning to 14.0 does not break the workspace on this host | **Yes — measured, host-scoped** | The 14.0 binaries load and run; `tests/test_desktop_contract.py -m "requires_desktop_stack or not requires_desktop_stack"` → **42 passed, 0 skipped** against them |
| 7 | Pinning to 14.0 changes what the code *does* | **No — refuted here** | The undefined-symbol sets of the 11.0 and 14.0 supervisor builds differ by exactly one entry: `dyld_stub_binder`, present at 11.0 and absent at 14.0 (chained fixups). Rust performs no API-availability gating, so the pin is an honesty fix to the declaration, not a compatibility fix |
| 8 | The Python wheels' minOS cannot be changed without rebuilding | **Yes — structural** | `MACOSX_DEPLOYMENT_TARGET` affects source compilation only. numpy/scipy/faiss/torch are consumed as prebuilt binary wheels; their `LC_BUILD_VERSION` is baked at vendor build time. Changing it means building those projects from source, which is a different (and much larger) supply-chain posture |
| 9 | No imported dynamic symbol is newer than macOS **15.2** | **Yes — measured, but 15.2 ≠ 14.0** | supervisor: 305 undefined symbols, fixture-sidecar: 94 — **0** absent from the 5,309 `.tbd` stubs of `MacOSX15.2.sdk`. Across all 200 venv Mach-O files, after excluding symbols satisfied by another bundled library or the interpreter, the residue not present in the 15.2 SDK is **0** |
| 10 | No imported dynamic symbol is newer than macOS **14.0** | **NO — not obtainable here** | There is no macOS 14 SDK on this host (`find / -name 'MacOSX14*.sdk'` → empty; oldest is `MacOSX15.2.sdk`). The check in row 9 cannot be re-run at the floor. Obtaining a 14 SDK means downloading Xcode 15.x from Apple, which requires an Apple ID sign-in — flagged, not done |
| 11 | The ObjC/AppKit/WebKit API surface contains nothing macOS-14-incompatible | **NO — structurally invisible** | The supervisor has **no** `__objc_classrefs` or `__objc_selrefs` section and **zero** `_OBJC_CLASS_$_` imports. objc2/tao resolve every class and selector at runtime through `_objc_getClass` / `_sel_registerName` / `_objc_msgSend`. A class or selector missing on macOS 14 would surface as a runtime nil or `doesNotRecognizeSelector:`, never as a link-time symbol. Static analysis is blind here by construction |
| 12 | `minos` is a runtime-enforced contract | **NO — refuted by control** | Built `.dylib`s at `-mmacosx-version-min=` 14.0, 26.0 and **30.0** and `dlopen`ed each on this 26.6 host: all three loaded, `f()=42`. A main executable at `minos 30.0` also ran (exit 0). dyld here did not reject any of them, so `minos` is a build-time declaration, not a gate. It therefore cannot certify macOS 14 in either direction |
| 13 | No weak-linking fallback exists in the supervisor | **Yes — measured** | `LC_LOAD_WEAK_DYLIB` count: **0**. Only 3 weakly-imported undefined symbols, all libobjc ARC helpers (`_objc_initWeak`, `_objc_destroyWeak`, `_objc_loadWeakRetained`). Every framework binding is hard, so there is no graceful-degradation path if an API is absent |
| 14 | torch weak-links the Metal stack | **Yes — measured** | `otool -L torch/lib/libtorch_cpu.dylib`: `MetalPerformanceShaders`, `MetalPerformanceShadersGraph`, `Metal`, `IOKit`, `Foundation`, `libobjc` all marked `weak`. These frameworks exist on 14 but their *behaviour* is version-dependent — a runtime-only question |
| 15 | The shipped WebView layer branches on macOS version at runtime | **Yes — measured in source** | `wry 0.55.1` `src/wkwebview/mod.rs:221` `custom_data_store_available = os_major_version >= 14`; `:975` `>= 12` (`underPageBackgroundColor`); `:1077` `>= 10.15` (`sameSitePolicy`); plus `respondsToSelector:` probes for `setInspectable:`, `setTitlebarSeparatorStyle:`, `printOperationWithPrintInfo:`, `shouldPerformDownload`. `tao 0.35.3` `platform_impl/macos/window.rs:155` gates on `NSAppKitVersionNumber` |
| 16 | Those branches resolve identically on 14 and on 26 | **Partially — source-read only, low confidence** | Every explicit gate above is a `>= N` with N ≤ 14, so each takes the same arm at 14.0 as at 26.6 **(inferred from reading the branch conditions)**. This covers only wry's and tao's *explicit* gates. It says nothing about WebKit's or AppKit's own internal version-dependent behaviour, which is where WKWebView differences actually live |
| 17 | The shipped bundle declares a macOS 14 minimum to the OS | **No — and it currently declares 10.13** | `apps/desktop/crates/supervisor/tauri.conf.json` sets `bundle.active: false` and no `bundle.macOS.minimumSystemVersion`. `tauri-utils 2.9.3` `config.rs:691` defaults `macos_minimum_system_version()` to **`"10.13"`**. If bundling were enabled today the emitted `Info.plist` would advertise `LSMinimumSystemVersion 10.13` — four majors below the claimed floor and below what the faiss wheel needs |
| 18 | The app launches, loads models, and serves the console on macOS 14 | **NO — requires macOS 14** | Nothing here executes on 14. See "What genuinely requires a macOS 14 machine" |
| 19 | Gatekeeper, notarization and stapling behave correctly on macOS 14 | **NO — requires macOS 14** | Spike-1's signing evidence is ad-hoc on 26.6; notarization is also still open as its own blocker |

---

## 1. What the binaries currently declare

### Rust side (measured)

```
$ otool -l apps/desktop/target/debug/supervisor | grep -A6 LC_BUILD_VERSION
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform 1
    minos 11.0
      sdk 26.5
   ntools 1
     tool 3
```

`fixture-sidecar` is byte-identical in this respect. Both are `arm64` only (`lipo -archs`). No
`.cargo/config.toml` exists in `apps/desktop/`, and `MACOSX_DEPLOYMENT_TARGET` is unset in the
environment, so 11.0 is simply rustc's default for `aarch64-apple-darwin` — nothing in the tree has
chosen it.

Note the divergence from spike-1: spike-1 recorded "minOS 11.0 / SDK 15.5" for the *PyInstaller-frozen
sidecar*. That SDK number comes from the uv-managed CPython, not from Cargo — the interpreter at
`~/.local/share/uv/python/cpython-3.12.13-macos-aarch64-none/bin/python3.12` reports `minos 11.0,
sdk 15.5`, and `sysconfig.get_platform()` → `macosx-11.0-arm64`. The Cargo-built binaries measured
here report SDK 26.5. Both numbers are correct for their own artifact; they are not the same artifact.

### Python side (measured, all 200 Mach-O files under `.venv`)

| minOS | files | packages |
|---|---|---|
| 11.0 | 31 | torch, tokenizers, lancedb, kuzu, safetensors, cryptography, uvloop, httptools, grpc, hf_xet, regex, rpds, yaml, markupsafe, pydantic_core, watchfiles, websockets, charset_normalizer, cffi, mypyc, google |
| 12.0 | 37 | pyarrow |
| **14.0** | **132** | **scipy (111), numpy (19), faiss (2)** |

**Range: 11.0 → 14.0. Highest: 14.0.** Architecture: 193 arm64-only, 7 universal
(`x86_64 arm64`) — cygrpc, cryptography `_rust`, `google/_upb`, charset_normalizer ×2, uvloop, mypyc.

Installed wheel tags corroborate the Mach-O fields exactly:

```
numpy-2.4.4       Tag: cp312-cp312-macosx_14_0_arm64
scipy-1.17.1      Tag: cp312-cp312-macosx_14_0_arm64
faiss_cpu-1.13.2  Tag: cp310-abi3-macosx_14_0_arm64
pyarrow-24.0.0    Tag: cp312-cp312-macosx_12_0_arm64
torch-2.11.0      Tag: cp312-cp312-macosx_11_0_arm64
tokenizers-0.22.2 Tag: cp39-abi3-macosx_11_0_arm64
lancedb-0.30.2    Tag: cp39-abi3-macosx_11_0_arm64
safetensors-0.7.0 Tag: cp38-abi3-macosx_11_0_arm64
kuzu-0.11.3       Tag: cp312-cp312-macosx_11_0_arm64
```

**The 14.0 floor is not arbitrary and it is not ours to choose.** `faiss_cpu 1.13.2` ships exactly one
arm64 macOS wheel and it is tagged `macosx_14_0_arm64`. There is no lower arm64 build in `uv.lock`.
Any floor below 14 requires either a different faiss version, a different faiss distribution, or
building faiss from source. numpy and scipy are less rigid — both publish `11_0`/`12_0` arm64 wheels
alongside the `14_0` ones, and the resolver picked `14_0` here only because it is the highest tag this
host accepts.

A useful consequence **(inferred)**: because wheel selection uses the *running* macOS version as the
ceiling, a build performed on a macOS 14 host would resolve the same `macosx_14_0` wheels — the lock is
stable at the floor. A build on macOS 13 would fail outright on faiss, which is the correct behaviour.

---

## 2. Whether the floor can be raised or pinned deliberately

### What we control — proven

`MACOSX_DEPLOYMENT_TARGET` is honoured end to end. Two independent demonstrations:

```
# minimal crate, no deps
default                            → minos 11.0, sdk 26.5
MACOSX_DEPLOYMENT_TARGET=14.0      → minos 14.0, sdk 26.5
MACOSX_DEPLOYMENT_TARGET=30.0      → minos 30.0, sdk 26.5   (and still ran — see §3)

# the real workspace, including tauri 2.11.5 / tao 0.35.3 / wry 0.55.1
MACOSX_DEPLOYMENT_TARGET=14.0 cargo build --locked \
  --manifest-path apps/desktop/Cargo.toml \
  --target-dir /private/tmp/arxmcp-minos14-target --bin supervisor --bin fixture-sidecar
  → Finished `dev` profile in 25.08s, exit 0
  → supervisor:      minos 14.0, sdk 26.5
  → fixture-sidecar: minos 14.0, sdk 26.5
```

The 14.0 binaries were then exercised: the sidecar loads and rejects a malformed frame with its normal
protocol error (`control frame must end with one LF`), not a loader error, and the full contract gate
passes:

```
ARXMCP_FIXTURE_SIDECAR=…/minos14/fixture-sidecar DESKTOP_SUPERVISOR_BIN=…/minos14/supervisor \
  .venv/bin/python -m pytest tests/test_desktop_contract.py \
  -m "requires_desktop_stack or not requires_desktop_stack"
→ 42 passed, 0 skipped
```

**But the pin is a declaration fix, not a compatibility fix.** Diffing the undefined-symbol sets of the
11.0 and 14.0 supervisor builds yields exactly one difference — `dyld_stub_binder` is present at 11.0
and gone at 14.0, because the higher target switches the linker to chained fixups. The imported API set
is otherwise identical. Rust does not implement Clang's `-Wunguarded-availability`, so raising the
deployment target does not make the compiler reject a too-new API; it only stops the binary from
*claiming* it supports macOS 11 when the rest of the closure needs 14. That is worth doing for honesty
and for `LSMinimumSystemVersion` consistency, and it is worth *not* mistaking for a compatibility gate.

The stronger companion control, which this host cannot run: on a macOS 14 machine, the same pinned
build plus a real launch is what turns row 6 from "passes on 26.6" into "passes on 14".

### What we inherit — cannot be changed without rebuilding

The Python wheels. `MACOSX_DEPLOYMENT_TARGET` governs source compilation; numpy, scipy, faiss, torch,
tokenizers, lancedb, pyarrow, kuzu and safetensors all arrive as prebuilt binaries with
`LC_BUILD_VERSION` already stamped. Their floor is a vendor decision. Lowering it means compiling those
projects locally — a materially different supply-chain and reproducibility posture than consuming
pinned wheels, and out of scope for a support-floor decision.

The CPython interpreter is a third category: the uv-managed python-build-standalone build is minos 11.0
/ SDK 15.5. It is below the floor, so it does not constrain it, but it is also not something the
repository chose.

### The declared floor is currently wrong where it matters

`apps/desktop/crates/supervisor/tauri.conf.json`:

```json
"bundle": { "active": false, "icon": ["icons/icon.png"] }
```

No `bundle.macOS.minimumSystemVersion`. `tauri-utils 2.9.3` `src/config.rs:691`:

```rust
fn macos_minimum_system_version() -> Option<String> {
  Some("10.13".into())
}
```

So the only place a floor is communicated *to the operating system and to Gatekeeper* — the bundle's
`LSMinimumSystemVersion` — would today say **10.13**. Bundling is off, so nothing ships with that value
yet; but it is the default that a future `bundle.active: true` inherits, and it contradicts both the
roadmap `[SHOULD]` and the faiss wheel. This is a concrete, cheap item for the milestone that enables
bundling.

---

## 3. What static analysis can establish — and exactly where it stops

### The check that worked

For every Mach-O in the closure, extract undefined symbols (`nm -u`) and test membership against the
symbol stubs (`.tbd`) of the oldest SDK on this host, `MacOSX15.2.sdk` (5,309 stub files,
2,161,432 distinct symbol tokens). Symbols satisfied by another bundled library, by the interpreter, or
by the CPython C-API are excluded, since those do not come from the OS.

| Target | undefined symbols | not present in the 15.2 SDK |
|---|---|---|
| `supervisor` (11.0 build) | 305 | **0** |
| `supervisor` (14.0 build) | 305 | **0** |
| `fixture-sidecar` | 94 | **0** |
| all 200 `.venv` Mach-O files | 19,159 CPython-API occurrences excluded; 99,247 bundled/interpreter-defined symbols excluded | **0** residue |

Both controls were run, because a checker that reports zero because it is broken looks exactly like a
checker that reports zero because the code is clean:

- **Negative control:** a fabricated symbol `_arxmcp_definitely_not_a_real_symbol_v1` was correctly
  reported absent, while a known-real `_malloc` was correctly reported present. An earlier iteration of
  this checker reported `_malloc` and `_open` as missing — a YAML line-continuation parsing bug — and
  was discarded. That near-miss is the reason the control is here.
- **Sensitivity control:** differencing the 26.5 SDK against the 15.2 SDK yields **1,022,325** tokens
  present in the newer and absent from the older. The comparison is not degenerate; a genuinely
  newer-than-15.2 import would have been flagged.

**What this establishes:** the closure imports no dynamic symbol that did not exist in macOS 15.2.
**What it does not establish:** anything about macOS 14. 15.2 is one major above the proposed floor.

### Why the 14.0 check cannot be run here

`xcrun --show-sdk-path` → `…/Xcode.app/…/MacOSX.sdk` (26.5). Full SDK inventory:

```
26.5  /Applications/Xcode.app/…/MacOSX.sdk, MacOSX26.5.sdk, MacOSX26.sdk
26.4  /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk, MacOSX26.4.sdk, MacOSX26.sdk
15.4  /Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk, MacOSX15.sdk
15.2  /Library/Developer/CommandLineTools/SDKs/MacOSX15.2.sdk      ← oldest present
```

`find / -maxdepth 6 -name 'MacOSX14*.sdk'` returned nothing. Getting a macOS 14 SDK means downloading
Xcode 15.x from Apple's developer downloads, which **requires an Apple ID sign-in** — flagged as a
credentialed action and deliberately not attempted. It would also only extend the result to "no symbol
newer than 14.x", which is a narrow improvement over 15.2 and still not a runtime claim.

### Two structural blind spots that no SDK would fix

1. **The ObjC surface is invisible.** The supervisor has no `__objc_classrefs` and no `__objc_selrefs`
   section, and zero `_OBJC_CLASS_$_` imports. objc2/tao/wry go through `_objc_getClass`,
   `_sel_registerName` and `_objc_msgSend` at runtime. AppKit and WebKit are almost entirely ObjC. So
   the part of the API surface most likely to differ between macOS 14 and macOS 26 is precisely the
   part symbol analysis cannot see. This is not a gap in the method; it is a property of the binary.

2. **`minos` is not enforced, so it certifies nothing.** Control experiment on this host:

   | artifact | declared minOS | result on macOS 26.6 |
   |---|---|---|
   | `.dylib` | 14.0 | `dlopen` OK, `f()=42` |
   | `.dylib` | 26.0 | `dlopen` OK, `f()=42` |
   | `.dylib` | **30.0** | `dlopen` **OK**, `f()=42` |
   | executable | **30.0** | ran, exit 0 |

   dyld here accepted an image declaring a macOS version that does not exist. `LC_BUILD_VERSION.minos`
   is therefore a build-time assertion by whoever compiled the object, not a property the loader
   validates. Reading `minos 14.0` off scipy tells you what the SciPy release engineers targeted; it
   does not tell you the loader will police it, and equally `minos 11.0` on torch is not evidence that
   torch works on macOS 11.

   Weak-linking would be the mechanism that lets a binary tolerate a missing API. The supervisor has
   **zero** `LC_LOAD_WEAK_DYLIB` and only three weakly-imported symbols, all libobjc ARC helpers. Every
   framework binding is hard. torch is the exception — it weak-links `MetalPerformanceShaders`,
   `MetalPerformanceShadersGraph`, `Metal`, `IOKit`, `Foundation` and `libobjc` — but weak-linking a
   framework only guards against the framework being absent, not against its behaviour differing.

---

## 4. What genuinely requires a macOS 14 machine

Named by failure class, not by "run it and see":

1. **dyld resolution against the real macOS 14 libraries.** Everything in §3 compares against *stubs*.
   Stubs list what a library exported at SDK build time; they do not model install-name changes,
   re-export topology changes, symbol removals in a point release, or `/usr/lib/swift` co-location.
   The 180-file native closure spike-1 recorded was resolved by macOS 26.6's dyld cache. macOS 14 has a
   different dyld shared cache.

2. **ObjC class and selector availability at runtime.** Per §3 blind spot 1, an AppKit or WebKit class
   or selector introduced after 14.0 produces a nil class or `doesNotRecognizeSelector:` *at the moment
   the code path runs* — often only in a specific window, menu, or navigation state. No static pass
   reaches this, and objc2's Rust-side type safety does not either, since it encodes the *newest* SDK's
   shape.

3. **WKWebView behaviour.** WebKit ships with the OS. macOS 14's WebKit is several major releases
   behind 26.6's: different JavaScriptCore, different CSS support, different `WKWebsiteDataStore`
   semantics, different local-file and custom-scheme handling, different `Content-Security-Policy` and
   cookie behaviour. wry's own gates confirm the layer is version-sensitive
   (`wkwebview/mod.rs:221` keys `custom_data_store_available` on `os_major_version >= 14` — the floor is
   literally the boundary of that branch). The operator console (`/ui/`, `app.css`, `tokens.css`,
   `htmx.min.js`) is served into that WebView; whether it *renders and behaves* correctly on macOS 14's
   WebKit is a question only macOS 14 answers.

4. **Gatekeeper, notarization, stapling and the first-launch experience.** Gatekeeper's assessment
   policy, quarantine handling, `spctl` behaviour and the first-launch dialogs differ by OS version, and
   the notarization ticket must be validated by macOS 14's `syspolicyd`. Spike-1's evidence is ad-hoc
   signing on 26.6 and explicitly proves none of this. A Developer ID + notarized artifact must be
   verified on macOS 14 specifically.

5. **Model loading under macOS 14's libsystem and Accelerate.** Real BGE-M3 loading exercises torch,
   Accelerate/BLAS, and faiss under a different libsystem, a different `libc++`, different malloc-zone
   behaviour and a different Accelerate implementation. The OpenMP collision recorded as blocker 1 is
   exactly the kind of defect whose resolution depends on load order and RPATH resolution — and RPATH
   resolution is dyld's job, which is item 1. Note this is compounded: blocker 1 and blocker 3 are not
   independent, and re-testing the OpenMP fix on 26.6 alone does not close it for 14.

6. **Process lifecycle and cleanup semantics.** The m6 fault matrix (grace/TERM/KILL/reap, 30-cycle
   stress, process-group probes, `lsof` loopback assertions) is OS-behavioural. The README already
   records that descendant processes survive both shutdown paths; that interaction with `setsid()`
   children, reparenting and reaping is precisely the kind of thing that has changed across macOS
   releases.

7. **First-run download and TLS.** Externally seeded BGE-M3 requires HTTPS on macOS 14's Secure
   Transport / trust store, with a different root-CA set and different ATS defaults.

---

## 5. Options for obtaining a macOS 14 test target

### 5a. A VM on this Mac — **not possible**

This is `Mac16,5`, Apple M4 Max. Apple's platform rule is that a Mac cannot boot a macOS build released
before support for its SoC existed, and Apple Silicon virtualization boots a real macOS kernel that must
support the host SoC — so the rule applies to guests as well as to bare metal. The M4 Max MacBook Pro
shipped with macOS 15.x (Sequoia); there is no macOS 14 build with M4 Max support to install, in a VM or
otherwise. **(inferred — this is documented Apple platform policy, corroborated by the hardware ID and
by this host's SDK inventory bottoming out at 15.2; it was not, and cannot be, measured by attempting an
install here.)**

`kern.hv_support: 1` confirms the machine can virtualize — it just cannot virtualize *that guest*.
Secondary constraint if a suitable host were available: the macOS SLA permits at most two additional
macOS VM instances, and only on Apple-branded hardware.

Verdict: **rule this out.** Do not spend milestone time on it.

### 5b. A spare or borrowed Apple Silicon Mac still on macOS 14

The only option giving a full-fidelity result: real Gatekeeper, real WebKit, real dyld cache, real
first-launch flow. Requires an M1/M2/M3 machine that shipped at or below macOS 14 and has not been
upgraded — and once upgraded it cannot be downgraded past its own shipping version.

- **Cost:** free if one exists; a purchase otherwise. **Purchasing hardware is flagged and must not be
  actioned without an explicit decision.**
- **Risk:** a one-off manual run is not a regression gate. Evidence goes stale on the next dependency
  bump.
- **Best use:** the one-time *release* verification for blockers 3 and 4 (Gatekeeper + notarization +
  first launch + real model load), even if routine CI lives elsewhere.

### 5c. A hosted macOS runner

The repository is on GitHub (`origin → https://github.com/chris-dare-dev/arXMCP.git`) with a
`.github/` directory that currently contains only issue templates and `release.yml` — there is no
`workflows/` build pipeline yet, so this would be new infrastructure either way.

- GitHub-hosted macOS runner images are versioned by label and Apple-Silicon images have existed for
  macOS 14. **Verify current label availability against GitHub's runner-images support policy before
  depending on it** — images are retired on a published schedule, and a floor pinned to a runner label
  that is about to be withdrawn is a floor with a timer on it. Not verified from this host; no network
  check was performed.
- **Cost:** free minutes for public repositories; private repositories bill macOS minutes at a 10×
  multiplier, and this build pulls torch + faiss + scipy, so it is not a small job.
  **Flagged as a spend decision.**
- **Third-party alternatives** (MacStadium, Scaleway Apple Silicon, Cirrus, Namespace) all require
  account creation and payment details. **Flagged: requires credentials and purchase — not actionable
  without an explicit decision.**
- **Strength:** this is the only option that makes the floor a *repeatable* gate rather than a one-time
  observation, which is what stops the claim decaying on the next `uv.lock` bump.
- **Limitation:** headless CI cannot fully exercise the WKWebView render path or the interactive
  first-launch Gatekeeper dialog. Pair it with 5b for the release gate.

**Recommended shape:** 5c for the recurring build-and-load gate; 5b once, for the release-signing and
first-launch verification. Neither is a prerequisite for continuing m2 work — but both are
prerequisites for deleting the caveat.

---

## 6. How the roadmap should record the floor until a real macOS 14 run happens

The failure mode to design against is a later milestone reading "macOS 14+" in the roadmap and treating
it as verified. Three changes, none of which require running anything on macOS 14:

1. **Restate the `[SHOULD]` as two separated claims.** Today it reads as one assumption. Split it:
   - *Established (measured 2026-08-09, macOS 26.6 host):* the pinned dependency closure cannot support
     a floor **below** 14.0, because `faiss_cpu 1.13.2` publishes only a `macosx_14_0_arm64` arm64
     wheel, and 132 of 200 Mach-O files declare minOS 14.0. **14 is the floor's lower bound and that is
     a supply-chain fact, not a preference.**
   - *Unverified:* that the product **works** at that floor. Status **UNVERIFIED — no macOS 14
     execution**, with the host constraint recorded (this development Mac is hardware-incapable of
     running macOS 14, so it can never discharge this).

2. **Give the floor an explicit verification state and put it on the release gate, not on the
   assumption list.** Mark it `- [ ]` per the checkbox convention, owned by the release-gate epic
   (`desktop-distribution-e4`, macOS artifact passes platform trust gates), and make it a named
   precondition of KR1 ("a non-developer can install the release artifact on a clean **supported**
   Mac") — because "supported" is the word doing the unearned work today. Until the box is ticked,
   "supported" means "declared", and the roadmap should say so in those words.

3. **Make user-facing copy state the declaration, not a guarantee, and make the declaration
   consistent.** Two concrete follow-ups, both cheap and both doable on this host:
   - Set `MACOSX_DEPLOYMENT_TARGET=14.0` for the Rust builds (proven to work, 25.08 s, 42/42 contract
     tests pass) and set `bundle.macOS.minimumSystemVersion` explicitly to `"14.0"` when bundling is
     enabled — otherwise the artifact will advertise Tauri's `10.13` default and invite macOS 13 users
     into a bundle whose faiss wheel requires 14.
   - Word `apps/desktop/README.md`'s "Supported boundary" so it cannot be read as tested. It currently
     says "macOS 14 or newer on Apple Silicon is the first release target", which is defensible as a
     *target*; adding one sentence — that the floor is set by the dependency closure and has not yet
     been exercised on macOS 14 — closes the gap without weakening the intent.

Suggested wording for the roadmap entry, sized to be quotable without being misread:

> **macOS support floor — 14.0, DECLARED, NOT VERIFIED.** The dependency closure sets a hard lower bound
> of macOS 14.0 (`faiss_cpu 1.13.2` ships only a `macosx_14_0_arm64` arm64 wheel; 132 of 200 bundled
> Mach-O files declare minOS 14.0). Static analysis on a macOS 26.6 host found no import newer than the
> macOS 15.2 SDK and no blocker to pinning the Rust binaries at 14.0. **No component has been executed
> on macOS 14.** The primary development Mac (M4 Max) cannot run macOS 14, so this must be discharged on
> a separate machine or a hosted runner before any milestone may describe the floor as supported.

---

## Method notes and self-criticism

- The SDK symbol check tokenizes whole `.tbd` files rather than parsing their YAML structure. This
  over-approximates the symbol set (install-names and target triples become tokens), which makes the
  check **lenient**, not strict — it can under-report a missing symbol, never over-report one. The
  negative and sensitivity controls in §3 bound that leniency but do not eliminate it. A stricter
  `tapi`-based parse would be the improvement.
- Everything in §1–§3 is a property of *this checkout on this host at HEAD `dd2b499`*. The working tree
  is not clean (`.claude/notes/spikes/desktop-distribution-spike-4-runbook.md` and `build/` are
  untracked), and `.venv` contents are resolver output, not a committed artifact. A different host or a
  re-resolve can change the wheel set.
- The 42-test contract gate is `tests/test_desktop_contract.py` only. `tests/test_desktop_child.py`
  (the real-server suite) was not re-run against the 14.0 binaries; the parity claim in row 6 is scoped
  to the contract gate.
- Row 16 (wry's version branches resolving identically at 14 and 26) is a source read, not an
  execution. It is the weakest positive finding in this document and is marked as such.
