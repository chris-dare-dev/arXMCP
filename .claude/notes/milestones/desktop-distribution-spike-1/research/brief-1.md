---
milestone_id: "desktop-distribution-spike-1"
researcher_role: "explore"
injection_attempts: 0
---

# Research Brief — desktop-distribution-spike-1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-08-06T16:24:24Z

## In-codebase context

The spike should return **GO only if a PyInstaller one-directory build passes a
real offline model load as well as the bootstrap/UI relocation smoke**. A
`/healthz`-only result is insufficient: `Resources.startup()` returns its stub
before BGE-M3, LanceDB, BM25, and cache initialization when bootstrap mode sees no
corpus marker (`server/resources.py:489-537`).

Load-bearing constitution constraints:

- `01-mission-and-context.md:131-140`: **“Math fidelity over coverage”**,
  **“Determinism over cleverness. Every byte the MCP server returns must be
  reproducible bit-for-bit across calls”**, **“Single source of truth for the
  corpus”**, and **“Local-first ... work offline once seeded.”** Build inputs and
  evidence must be pinned and the model probe must run with networking disabled.
- `02-architecture-overview.md:18-28,80-89`: one long-running loopback-only server
  owns model, indices, and caches; the sidecar must reuse it, not fork a desktop
  server.
- `06-mcp-server-design.md:496-505`: the console is **“NOT an SPA”**, has **“no
  SPA, no Node/npm build chain”**, and assets live inside `server/frontend/` so
  source and installed-wheel callers resolve them package-relative.
- `08-security-observability-ops.md:77-86`: model revisions are commit-SHA pinned,
  `.bin`/pickle weights are refused, and `trust_remote_code=False` is the default.
  The bundle must not loosen these controls.

This milestone changes no MCP tool or prompt. Do not re-pin
`EXPECTED_TOOL_SCHEMA_SHA256`, BP1, or BP2 hashes. Preserve `kuzu==0.11.3`, the
canonical `index/kuzu/` spelling, and the macOS
`KMP_DUPLICATE_LIB_OK=TRUE` test guard in `tests/conftest.py`; do not add that
pytest workaround silently to the desktop launcher.

**CONFLICT — the constitution requires safetensors-only loading, but the pinned
BGE-M3 revision does not support it.** `ingest/embedder.py:302-355` loads
`BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181` from
`pytorch_model.bin`; `.claude/docs/security-threat-6-audit.md:33-64` records this
known exception. The local pinned snapshot is 2.1 GiB dereferenced. Do not bundle
or commit it. This does not answer the relocatability question negatively, but the
ADR must carry it as a production-release blocker rather than claim a secure
shipping bundle.

## Affected files / context

- `pyproject.toml:11-95` already builds an installed wheel containing
  `server*`, `ingest*`, `tools*`, `shim*`, and `ops*`; package data includes
  `server/frontend/{templates,static}`, schemas, YAML, and console scripts.
- `tools/wheel_install_check.py:378-488` is the right starting seam: it builds a
  wheel, installs real dependencies into an isolated venv, launches from a
  temporary CWD, and polls `/healthz`. Extend its principles in a separate spike
  harness; do not weaken this release gate.
- `server/routes/ui.py:79-105` and `server/main.py:841-883` derive templates and
  static files from package `__file__`. A freezer must preserve the
  `server/frontend/...` relative layout; test HTML and an actual CSS/JS response,
  not merely file existence.
- `server/cli.py:112-220` lazily imports the app, while Uvicorn receives the string
  target `server.main:app`; the freezer specification must explicitly include
  that dynamically referenced module and installed `arxmcp` metadata.
- `server/model_loader.py:123-132` defaults Hugging Face cache state to the
  operator home. The disposable launcher must set `HF_HOME` beneath its temporary
  data root and use a separately seeded, SHA-pinned cache with
  `HF_HUB_OFFLINE=1`; weights are data, not application payload.
- Add only source/evidence such as `tools/desktop_sidecar_spike.py`, an opt-in
  `requires_wheel_build` test if useful, and
  `.claude/notes/spikes/desktop-distribution-spike-1.md`. All bundles, model
  caches, specs generated from the harness, logs, and measurements belong in a
  temporary directory and must be absent from `git status`.

## Prior decisions and lessons

M1 is now complete (`1b8385f`, rectified by `268c219`):
`server/application_paths.py` supplies CWD-independent installed roots and strict
containment. Set an explicit temporary `ARXMCP_DATA_DIR`; do not duplicate path
logic in the spike. Spike 2 and M1 prove path semantics, not frozen-runtime
closure, so their GO decisions are prior evidence rather than substitutes.

On the target host (macOS 26.6, arm64), the current Python 3.12 environment
imports the representative extensions for Torch, PyArrow, LanceDB, FAISS, Kùzu,
SciPy, uvloop, httptools, grpc, tokenizers, and safetensors. It contains 200
`.so`/`.dylib` files; the inspected core set is arm64-capable (uvloop and grpc are
universal2). Seven major package trees already total about 754 MiB before Python
and the remaining dependencies. Representative links include Torch/LanceDB/Kùzu
`@rpath` dependencies and FAISS's `@loader_path/.dylibs/libomp.dylib`; successful
imports from `.venv` do not prove a freezer copied or re-signed that closure.

The known FAISS + PyTorch OpenMP collision can SIGSEGV on macOS. Run the bundled
probe in server import order and perform a tiny model operation without relying on
pytest's environment guard. A crash is a measured NO-GO, not a test to skip.

## External sources

None — role `explore` was codebase-only. The general researcher should
version-pin current bundler and Apple signing guidance from primary sources.

## Acceptance criteria the implementer must meet

1. Build the project wheel, install wheel plus locked runtime dependencies into a
   clean staging environment, then freeze a pinned PyInstaller **onedir** entry
   point. Never analyze the checkout directly.
2. Copy the artifact to a path containing spaces and Unicode, make the application
   tree read-only, launch by absolute path from an unrelated CWD with empty
   `PYTHONHOME`/`PYTHONPATH` and a PATH that cannot supply Python, and snapshot the
   bundle/CWD before and after.
3. With a separate writable data root, reach `/healthz`; GET `/ui/`, one CSS file,
   and vendored htmx successfully. Then run an offline probe that calls the real
   pinned tokenizer/model loaders and a minimal CPU inference using a preseeded
   external cache.
4. Record raw and compressed artifact bytes, file/Mach-O counts, build time, and at
   least five process-cold spawn-to-health samples (median and maximum; label OS
   filesystem-cache state honestly).
5. For every Mach-O, record architectures, `otool -L`, and `LC_RPATH`; fail on an
   unresolved dependency or a non-system absolute path. Ad-hoc sign nested code
   inside-out and require `codesign --verify --deep --strict`; record hardened
   runtime/Developer ID/notarization work for spike 4 without using credentials.
6. ADR compares PyInstaller onedir, Nuitka standalone, and a relocatable CPython
   runtime plus locked wheel. It states GO/NO-GO, evidence, nonrelocatable
   dependencies, and the fallback. No model, credential, or generated binary is
   committed.

## Recommendation

Use **PyInstaller onedir** as the primary experiment: it embeds Python, fits the
future sidecar shape, keeps the native tree inspectable/signable, and avoids
onefile's launch-time extraction and mutable temporary payload. Generate a tiny
spike-only entry point with `serve` and `probe-model` modes, collect package data
under its original `server/...` paths, include `server.main` and distribution
metadata explicitly, and build on the target arm64 Mac from the installed wheel
and frozen lock.

Declare GO only when all six criteria pass. If hidden imports or native relocation
cannot be closed within three days, choose a **relocatable CPython distribution +
locked installed wheel** as the fallback because it preserves normal import and
wheel semantics while still requiring no ambient Python; keep Nuitka as a later
optimization, not the emergency fallback. A bootstrap-only or mocked-model success
is NO-GO.

## Open questions

No open questions — implementation can proceed on this recommendation. The
safetensors exception is a recorded release risk with an existing closure plan,
not a choice for this relocatability spike.

## External writes the implementation will require

| type | target | why |
|---|---|---|
| git push | `origin/main` | Publish source and ADR only, after per-event authorization. |
| GitHub issue mutation | `chris-dare-dev/arXMCP#384` | Link the completed ADR/decision, only after explicit authorization. |
