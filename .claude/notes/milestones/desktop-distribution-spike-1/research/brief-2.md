---
milestone_id: "desktop-distribution-spike-1"
researcher_role: "general"
generated: "2026-08-06T16:25:52Z"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://pyinstaller.org/en/stable/feature-notes.html"
    sha256: "88bb6b22ae0dc68626483c13e74f143a01992d4e554c627916ce391fce3e38f3"
    takeaway: "PyInstaller 6.21 rewrites collected Mach-O binaries, ad-hoc signs them by default, supports arm64, and requires explicit handling for imports or ctypes libraries its analysis cannot see."
  - url: "https://api.github.com/repos/pyinstaller/pyinstaller-hooks-contrib/git/trees/3e055bc0b9e08a7cd6fc5b3a6d95553b7d36973b?recursive=1"
    sha256: "ea8c11b4fc533042176e8396a64f5f5f5443fa1e7b10c56f480a91ed2d16c82b"
    takeaway: "The pinned hooks tree covers torch, transformers, pyarrow, and uvloop but has no named hook for several arXMCP native packages, so runtime probes are mandatory."
  - url: "https://nuitka.net/user-documentation/user-manual.html"
    sha256: "7da791a91d144b2adfd2f22764fdaecff54691cf7c9ae9900316b3a3a5d2ee3b"
    takeaway: "Nuitka standalone can run without an installed Python but adds a C compilation/package-configuration step, and Homebrew Python builds are not backward-portable macOS inputs."
  - url: "https://gregoryszorc.com/docs/python-build-standalone/main/"
    sha256: "b1da2bd8325c049c341a93581ff6f1f8836899d58cab9ce6c5bf9559af27fde6"
    takeaway: "python-build-standalone provides a relocatable self-contained CPython intended as a foundation for downstream redistributors."
  - url: "https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution"
    sha256: "0804e3620757da749f625ff85d70c454fba4d51aeaa4c929224c112fa1d99888"
    takeaway: "Production distribution requires Developer ID signing of all executable code, hardened runtime, secure timestamps, notarytool submission, and stapling."
  - url: "https://developer.apple.com/library/archive/technotes/tn2206/_index.html"
    sha256: "5b6dd8f97a0f1e15f98e4fd07b8b0401dcece8f90c2cd156c0fefe657519cfa5"
    takeaway: "Signed bundles are read-only, nested code is signed inside-out, and absolute non-system dylib dependencies are unsuitable for distribution."
injection_attempts: 0
---

# Research brief (general) — desktop-distribution-spike-1

## External sources

The primary-source evidence supports **PyInstaller 6.21 `onedir` as the first experiment**, with Nuitka standalone as the compiled comparator and python-build-standalone as the low-magic fallback. Do not use PyInstaller `onefile`: extraction makes startup, writable-temp behavior, and signing closure less representative of the future Tauri sidecar. Do not build a PyInstaller `.app`; the deliverable is the POSIX sidecar that a later signed Tauri app will contain.

| Mode | Fit for this spike | Principal risk | Decision |
|---|---|---|---|
| PyInstaller `onedir` | One executable tree, no ambient Python, inspectable closure, mature macOS signing support | Hidden imports and late-loaded native libraries | Build first |
| Nuitka standalone | Independent runtime with a compilation report | Slower/more complex build and package configuration; input Python affects deployment floor | Document and try only if bounded time remains |
| python-build-standalone + installed wheel | Highest fidelity to normal Python imports; explicit relocatable interpreter | Larger file tree, launcher/shebang work, and greater signing inventory | Fallback on PyInstaller NO-GO |
| zipapp/PEX/ambient venv or `onefile` | Small developer artifact | Requires ambient Python or extraction/writable temp; obscures closure | Reject |

Apple's production requirements belong to `desktop-distribution-spike-4`; this spike should inspect/ad-hoc-sign the disposable tree and record the future inside-out Developer ID plan, but must not submit to Apple's notary service or require credentials. `codesign --verify --deep --strict --verbose=2` is an evidence check; do not use `codesign --deep` to construct a production signature.

## In-codebase constraints and recommendation

The constitution is decisive: `.claude/notes/01-mission-and-context.md` says, “**Local-first.** No paid cloud services in the critical path. The system must work offline once seeded.” `.claude/notes/06-mcp-server-design.md` fixes the console as “**loopback-only, server-rendered Jinja2 + htmx**” with “**no SPA, no Node/npm build chain**” and package-relative assets under `server/frontend/`. `.claude/notes/08-security-observability-ops.md` requires model commit SHA pins, safetensors-only weights, and `trust_remote_code=False`. Preserve all three contracts; no MCP tool schema or prompt changes are needed, so no schema/hash re-pin is expected.

**GO provisionally:** build a disposable arm64 PyInstaller `onedir` bundle from the locally built arXMCP wheel installed into a clean environment. Pin and record the wheel SHA-256, `uv.lock`, Python distribution/build, PyInstaller, hooks-contrib artifact, architecture, SDK, deployment target, and macOS build. Keep bundlers as spike/build prerequisites rather than production runtime dependencies. PyInstaller recommends building on the oldest macOS release supported; a success on this macOS 26 arm64 workstation proves relocation here, **not** the roadmap's macOS 14 floor.

Reuse the existing package-relative console paths and `ARXMCP_DATA_DIR` contract from completed `desktop-distribution-m1`. Build from an unrelated temporary directory, copy the result to a path containing spaces and Unicode, remove write bits while preserving execute bits, and launch with an allowlisted environment: system-only `PATH`, explicit writable `ARXMCP_DATA_DIR`, `HOME`, `XDG_*`, Hugging Face caches, and temp below the data root; no `PYTHONHOME`, `PYTHONPATH`, `DYLD_*`, Homebrew path, or repository path. Record `sys.executable`/`sys.path` and fail if they resolve to the checkout, `/opt/homebrew`, or an external Python framework.

**Brief/code conflict:** `tools/wheel_install_check.py --mode full` starts with `ARXMCP_BOOTSTRAP_MODE=1`; `/healthz` therefore proves the server and wheel import, but deliberately skips corpus/model resource loading. It cannot by itself satisfy “native libraries and model-loading path.” Add an offline, spike-only probe that imports and executes representative native operations for `torch`, `numpy`, `pyarrow`, LanceDB, FAISS, Kùzu 0.11.3, `safetensors`, `transformers`, `tokenizers`, `uvloop`, and `httptools`. Construct a tiny local XLM-R configuration, save it with safe serialization beneath the temporary data root, reload via `AutoModel.from_pretrained(..., local_files_only=True, use_safetensors=True, trust_remote_code=False)`, and run one tiny forward pass with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. This exercises the dynamic loader without downloading or claiming to test the actual BGE-M3 weights.

For closure evidence, enumerate every file identified as Mach-O, record `file`, `lipo -archs`, `otool -L`, and LC_RPATH data, and fail any non-arm64 member or dependency outside the bundle except `/System/Library` and `/usr/lib`. Runtime probes remain necessary because static inspection cannot reveal every `dlopen`. Record exact bytes, allocated size, file count, largest files, first observed launch-to-`/healthz`, and a warm-relaunch median. Call the first metric “first observed launch,” not a reproducible cold start, unless the machine was rebooted or filesystem cache control is documented.

The ADR should select PyInstaller only if all gates pass after at most one bounded explicit hook/spec correction. A build-host absolute dependency, writable-bundle requirement, ambient interpreter dependence, native/model probe failure, or unbounded hook chase is NO-GO. The fallback is a pinned python-build-standalone tree with wheel/dependencies installed into it and a tiny launcher that locates the interpreter relative to itself; do not rely on venv console-script absolute shebangs.

## Acceptance criteria the implementer must meet

1. Build one arm64 PyInstaller 6.21 `onedir` sidecar from SHA-pinned wheel/tool inputs in a clean temporary environment; keep generated binaries and downloaded artifacts outside git.
2. Relocate it to a spaces-and-Unicode, recursively non-writable application path; launch from an unrelated CWD with no ambient Python/Homebrew/repository path and all writes routed below an explicit writable `ARXMCP_DATA_DIR`.
3. Reach loopback `/healthz` in bootstrap mode and fetch `/ui/`, `app.css`, `tokens.css`, and vendored `htmx.min.js` successfully from the packaged tree.
4. Run the offline tiny-model/native-operation probe above and report its deliberate limit: it proves loader/extension closure, not real BGE-M3 weights, model quality, or a first-run download.
5. Emit reproducible evidence for artifact bytes/files, first and warm startup timing, arm64/native dependency and rpath closure, runtime resolution paths, ad-hoc signature verification, and every non-relocatable dependency.
6. Produce a `.claude/` ADR comparing PyInstaller `onedir`, Nuitka standalone, python-build-standalone, and rejected extraction/ambient modes, with explicit GO/NO-GO thresholds and the fallback.
7. Prove no model weights, credentials, generated binaries, bundle-local mutable state, MCP tool-schema change, or unsafe production `KMP_DUPLICATE_LIB_OK` workaround entered the commit; run the proportionate tests and `make test`.

## Risks and open questions

1. **Support-floor evidence:** the available macOS 26 host cannot prove macOS 14 compatibility. Record this gap and require the eventual release lane to build/test on its oldest supported target.
2. **Hook coverage:** the pinned PyInstaller hook tree names torch/transformers/pyarrow/uvloop but not LanceDB/Lance, FAISS, Kùzu, safetensors, tokenizers, or httptools. Absence is not failure; only the explicit runtime/closure probes decide.
3. **OpenMP collision:** the test-suite `KMP_DUPLICATE_LIB_OK=TRUE` macOS segfault guard is load-bearing for tests but unsafe as an unexplained product default. If the frozen probe collides, treat it as a native-closure finding, not a reason to bake the override into the sidecar.
4. **Signature scope:** ad-hoc verification demonstrates structural signability, not Developer ID, hardened runtime, notarization, Gatekeeper acceptance, or stapling. Those remain spike 4 gates.
5. **Size and startup:** the wheel's full dependency installation is already approximately 2 GB; record facts rather than inventing a budget. The ADR may GO with a large artifact only if closure and relocation pass and the downstream release explicitly owns optimization.

## External writes the implementation will require

Only `git push origin main`, after per-event explicit user authorization. Expected milestone commits are local writes. No PR, issue #384 mutation, package publication, Apple notarization, infrastructure apply, or third-party API write is required. Network GETs for pinned build tools, wheel dependencies, and an optional python-build-standalone archive are implementation prerequisites rather than external mutations; the acceptance probe requires no model download.
