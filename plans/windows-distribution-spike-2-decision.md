# Windows frozen-runtime relocation decision

Status: **UNCERTAIN — transfer-ready; clean-host proof pending**
Decision date: 2026-08-08
Roadmap: `plans/windows-distribution/roadmap.yaml`
Tracking issue: https://github.com/chris-dare-dev/arXMCP/issues/411

## Decision

Use PyInstaller `onedir` as the current Windows x64 frozen-runtime baseline. The generated bundle is self-contained and transfer-ready on the build host, but it is not yet a clean-host-qualified product artifact. Do not claim dependency closure or write confinement until a distinct reverted or factory-clean Windows host supplies the required runtime trace.

The first freezer specification must explicitly collect `latex2mathml` package data, including `unimathsymbols.txt`; the initial build exposed that missing-data requirement.

## Evidence

- PyInstaller 6.21.0 produced a Windows `onedir` server/shim artifact containing 5,635 files and 960,628,223 bytes.
- The complete transfer bundle contains 5,759 files and 3,269,654,121 bytes, including the artifact, pinned model snapshot, fixture, and a 78-line target-only PowerShell probe.
- The target probe contains zero forbidden references to the repository, Git, `.venv`, ambient Python, PyInstaller, global caches, or prior evidence.
- One detached whole-transfer SHA-256 manifest validated before and after the fresh-copy run with zero mismatches.
- From a neutral current-host copy, `/readyz` returned 200, `/ui/` and its referenced asset returned 200, the frozen shim exited 0 and listed 8 tools, and the server shut down gracefully with exit 0.
- The staged offline model resolved `BAAI/bge-m3` revision `5617a9f61b028005a4858fdac845db406aefb181` from the bundled cache.
- These facts establish transfer readiness only. There was no distinct clean host, effective read-only ACL proof, verified network block, or authorized process-tree DLL/write trace, so all three product criteria remained unmeasured.

## Clean-host promotion gate

1. Use a separately identified Windows environment reverted to a documented clean snapshot or a factory-clean physical host.
2. Stage the manifest-bound transfer as administrator, grant the standard test user read-and-execute only, and prove application-directory writes fail while the application-data root remains writable.
3. Verify no ambient Python, Git, checkout markers, prior run-data, or global model cache exists, and block target network use.
4. With explicit owner authorization, capture a process-tree Load Image and filesystem trace using Microsoft Sysinternals Process Monitor. Do not install or execute Process Monitor without that authorization.
5. Require `/readyz`, `/ui/` plus an asset, initialized MCP `tools/list`, pinned offline model discovery, and graceful bounded shutdown to pass.
6. Require zero missing runtime dependencies, zero writes outside `ARXMCP_DATA_DIR`, and unchanged whole-transfer manifests before and after execution.

Until this gate passes, describe the artifact as **Windows x64 transfer-ready**, not **clean-host supported**.

Canonical local evidence: `.claude/notes/spikes/windows-distribution-spike-2/`.
