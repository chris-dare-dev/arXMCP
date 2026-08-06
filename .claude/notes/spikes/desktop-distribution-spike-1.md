# ADR — relocatable bundled sidecar spike

**Status:** Accepted for m2 feasibility; **NO-GO for release readiness**
**Date:** 2026-08-06
**Milestone:** `desktop-distribution-spike-1` / issue #384

## Decision

Proceed to m2 with PyInstaller 6.21 `onedir` as the provisional sidecar mode. On this macOS 26.6 arm64 host, the installed-wheel bundle relocated, ran read-only without ambient Python, served the console, and completed the combined native/tiny-model probe. Do not release it: the installed-wheel OpenMP collision, real-model exception, support-floor gap, and production signing gates remain open. If PyInstaller cannot close those gates, fall back to python-build-standalone plus the locked installed wheel.

## Pinned experiment

- Base `10b8641a509b140ab5dcfd3e132e9578a169531a`; `uv.lock` SHA-256 `6d08359afb8b3901083ab7179aeeb95e32f8e4a5ca9cc82169c8fa2870f5ef75`.
- Final installed arXMCP wheel SHA-256 `d1a89495264e33ba360dcf5a6b124cc83423ba0bcfdfa76a2de980b1876d4d6a`.
- PyInstaller 6.21.0 wheel SHA-256 `327d132389f37912609e01be62810cf96b5aa95b613903e4b8692e0d12fb0eda`; hooks-contrib 2026.6 SHA-256 `fd13b8ac126b35361175edacd41a0d97080b75dd5f4b594ecefefff969509dd3`.
- Python 3.12.13; macOS 26.6 build 25G5028f arm64; SDK 26.5. The executable reports minOS 11.0 / SDK 15.5, but this run proves only this host—not macOS 14.
- The wheel, locked staging environment, tool wheels, spec, build/dist trees, model, caches, logs, archive, and raw evidence stayed under `/private/tmp/arxmcp-sidecar-spike1.hAKhhD`; none is committed.

## Measured evidence

| Gate | Result |
|---|---|
| Final corrected build | 74.04 s; one bounded spec correction added `latex2mathml/unimathsymbols.txt` after the first server launch exposed its absence |
| Relocation | `/private/tmp/.../Relocated Sidecar – α/应用 Bundle`; absolute launch from read-only `unrelated cwd – β`; application tree had zero writable entries |
| Artifact | 1,107,353,958 raw bytes; 1,119,813,632 allocated bytes; 262,826,333-byte ZIP; 5,549 files |
| Startup | first observed 6.4388 s; four warm process relaunches 0.5379/0.5923/0.5348/0.5409 s; warm median 0.5394 s; max 6.4388 s |
| Bootstrap/UI | `/healthz` 200 `{"status":"ok"}`; `/ui/` 6,671 B; `app.css` 37,905 B; `tokens.css` 19,451 B; `htmx.min.js` 51,439 B, all 200 |
| Immutability | Bundle and unrelated-CWD manifests were identical before/after five processes; all mutable state was below explicit `ARXMCP_DATA_DIR` |
| Native closure | 199 Mach-O files, all arm64-capable; every `otool -L` dependency and LC_RPATH recorded; zero unresolved dependencies and zero non-system absolute dependencies |
| Host paths | Runtime guard required `sys.executable` and every `sys.path` entry under the bundle; binary scan found no checkout, staging, `/Users/chris.dare`, or `/opt/homebrew` string |
| Signing | Every nested Mach-O ad-hoc signed inside-out; per-file strict verification and `codesign --verify --deep --strict` passed; signature flags are explicitly `adhoc`, TeamIdentifier unset |
| Offline probe | FAISS search, NumPy, PyArrow, LanceDB, Kùzu, uvloop, httptools, tokenizers, and tiny XLM-R safetensors save/reload/forward passed; output shape `[1,3,8]` |
| Loader pins | Imported real arXMCP loaders and validated BGE-M3 `5617a9f61b028005a4858fdac845db406aefb181` and reranker `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |

“First observed” is not reboot-cold; the later samples are filesystem-cache-warm. The tiny local model proves loader and extension closure only—not BGE-M3 weights, quality, or first-run download.

## OpenMP finding

The clean installed-wheel probe (LanceDB/FAISS then Torch, no workaround) aborted with OpenMP Error #15. The frozen probe passed because FAISS `_swigfaiss.abi3.so` has `LC_RPATH @loader_path/..` and resolves `_internal/libomp.dylib` (SHA-256 `cc166d…`), not its redundant nested `faiss/.dylibs/libomp.dylib` (`798920…`). This supports m2 feasibility but is still a release blocker until the library consolidation is intentional and regression-tested. `KMP_DUPLICATE_LIB_OK` is forbidden by the probe and was never used.

## Alternatives

| Mode | Decision | Reason |
|---|---|---|
| PyInstaller `onedir` | Proceed to m2 | No ambient Python, inspectable/signable tree, host relocation passed |
| Nuitka standalone | Comparator only | Adds C compilation and package-specific configuration without reducing the present release gates |
| python-build-standalone + wheel | Fallback | Highest fidelity to normal import/wheel semantics while remaining relocatable |
| PyInstaller `onefile`, zipapp, PEX, ambient venv | Reject | Extraction or ambient Python does not answer the immutable sidecar question |

## Release blockers

1. Close and regression-test the installed-wheel FAISS/Torch OpenMP collision without `KMP_DUPLICATE_LIB_OK`; remove redundant copied native libraries.
2. Exercise real externally seeded BGE-M3. Its pinned revision still uses a roughly 2.1 GiB `pytorch_model.bin`, a known safetensors-policy exception; no model belongs in the application bundle.
3. Build and test on the oldest supported macOS target. This macOS 26.6 run makes no macOS 14 compatibility claim.
4. Complete inside-out Developer ID signing with hardened runtime, secure timestamps, notarization, stapling, and Gatekeeper verification. Ad-hoc success proves none of those.
5. Productize the `latex2mathml` data hook and `multiprocessing.freeze_support()` entry behavior; retain the sanitized unrelated-CWD/read-only/native/model gates.

## Consequences

m2 may design a production sidecar boundary around `onedir`, external application data, and external model caches. Release remains blocked; python-build-standalone is the named fallback rather than an unbounded PyInstaller hook chase.
