# Critique — desktop-distribution-m2 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** 092ab7b5f6e6d30dd2b6358074d0a7b97b12d57d..3e2dd21819f7cf2ce8d5cb26934c8c59194b5253
**Diff stats:** 9 files, 952 LOC (901 additions, 51 deletions)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The selected-root wiring is correct for the consumers this range changes, and the installed-wheel gate now proves substantially more than path-string resolution: it boots the installed entry point outside the checkout, performs real writes, inventories watched trees, and preserves the frozen MCP/cache surface. One HIGH remains in the installed server's ordinary UI workflow, however. The ingest child reaches `tools.notebook_ingest`, but that wrapper passes explicit notebook LanceDB/log paths while leaving ar5iv, parsed-corpus, chunk, embedding, and ops writers on import-time `REPO_ROOT/var/arxmcp` defaults. In a wheel those defaults are beside `site-packages`; the new smoke creates a notebook but never starts ingest, so both the runtime defect and the watched-venv mutation remain invisible. The second finding is confined to proof strength: the wheel-import provenance check uses a textual prefix rather than canonical path containment.

## Executive summary

- [HIGH] The installed UI ingest subprocess still sends parsed HTML, chunks, embeddings, and ingest statistics to package-root defaults; the full-wheel smoke stops after notebook creation and never exercises that path.
- [MEDIUM] The wheel provenance check accepts a textual path prefix, so a sibling-prefix path or a symlink below `site-packages` can satisfy the check without the imported module being canonically contained there.
- [CLEAN] Config-owned notebook and corpus paths now reach the changed HTTP, UI, retrieval, and MCP-resource consumers while existing slug and symlink rejection remains intact.
- [CLEAN] The child environment is scrubbed before import and redirects application, HOME/XDG, model, plotting, loader, Python, and temporary state below the selected root.
- [CLEAN] `server/tools.py`, prompts, result envelopes, and schema pins are untouched; MCP resources retain deterministic JSON serialization and delimiter wrapping.
- [CLEAN] Math fidelity, no-fork, tier sequencing, loopback binding, Kùzu pin/path, and the macOS `KMP_DUPLICATE_LIB_OK` guard are unchanged.
- [CLEAN] Six new focused tests pass; the implementation records a green full wheel check and `make test` result of 5,014 passed, 47 skipped, 1 xfailed with Ruff clean.

## Findings

**H1 — Installed UI ingest still writes through package-root defaults, outside the selected data root** (HIGH)

**Where:** `tools/wheel_install_check.py:721`
**Anchor:** `            _post_smoke_notebook(port)`
**What:** The live portion of the new smoke creates a notebook and then switches to the standalone `_WRITER_PROBE`; it never POSTs `/ui/api/notebooks/{slug}/ingest`. That omitted server path spawns `sys.executable -m tools.notebook_ingest` (`server/ingest_tracker.py:232-239`). The child correctly resolves its notebook directory from `ARXMCP_DATA_DIR`, but `tools/notebook_ingest.py:107-112` passes only the notebook LanceDB and log/failure paths to `run_bulk_ingest`. The remaining defaults still come from the installed module location: `ingest/ar5iv_fetch.py:53-55` derives ar5iv and parsed roots from `REPO_ROOT`, `ingest/chunker.py:77-80` derives parsed/chunks/chunk-log roots from `REPO_ROOT`, `ingest/embedder.py:160-165` derives chunks/embeddings/stats/log roots from `REPO_ROOT`, and `ingest/store.py:125-127` derives store statistics from `REPO_ROOT`. `ingest/bulk_ingest.py:330,343,349` then calls `chunk_paper`, `embed_paper`, and `load_embed_record` without overriding those paths. In an installed wheel, these are paths beside the package in the venv rather than children of `Config.application_paths.root`; on a read-only installation ingest fails, and on this writable test venv it mutates the watched installation tree. A direct installed-mode import reproduced the split: Config selected the temporary data root while ar5iv, parsed, chunks, embeddings, embed stats, and store stats all resolved under the module checkout's `var/arxmcp` analogue.
**Why it matters:** Notebook ingest is the primary mutation launched from the loopback operator console. An installed server can pass `/healthz`, notebook creation, and every new confinement assertion yet fail its main data-producing workflow or write corpus/cache/ops state into `site-packages`. That violates the local-first single-root contract, makes uninstall/reinstall capable of discarding user state, and means the regression explicitly intended to catch repository/package-derived writable defaults has a production-sized blind spot.
**Proposed fix:** Thread the live `ApplicationPaths` corpus, cache, and ops children through `IngestTracker` → `tools.notebook_ingest` → `run_bulk_ingest` and onward into `chunk_paper`, `embed_paper`, `load_embed_record`, and store-stat writers. Preserve the existing source-mode defaults for offline CLIs, but make the server-launched child receive explicit paths (arguments or a validated absolute data-root environment) rather than rebinding mutable globals. Extend the full-wheel gate with a deterministic, network-free ingest-child probe that reaches the same server subprocess boundary and proves every produced path is beneath the selected root while the venv, checkout, and CWD manifests remain unchanged.
**Regression-guard:** `tests/test_installed_path_consumers.py::test_server_ingest_child_uses_application_paths` should launch the real child boundary with poisoned package/CWD defaults and assert parsed, chunk, embedding, store-stat, and failure/log writes land below Config; the opt-in `make wheel-check-full` should exercise the same installed child with deterministic local input.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint

**M1 — Wheel provenance uses textual prefixing instead of canonical containment** (MEDIUM)

**Where:** `tools/wheel_install_check.py:647`
**Anchor:** `        if not resolved.lower().startswith(site_packages.lower()):`
**What:** The claimed proof that `server.__file__` is below the fresh venv's `site-packages` lowercases two strings and compares their prefixes. This accepts a sibling such as `/venv/lib/site-packages-shadow/server/__init__.py`, and it accepts a path lexically below `site-packages` whose file or ancestor is a symlink to the checkout. Neither case is canonical containment, and string lowercasing is not the platform path model the rest of this milestone deliberately uses.
**Why it matters:** The full wheel check's later filesystem conclusions are meaningful only if the process under test actually imported the installed copy. A false provenance pass can turn the strongest pre-publish evidence into another source-checkout run, especially on a development venv containing `.pth` or symlink-based tooling. This is a test-proof weakness rather than evidence that the clean venv currently takes the wrong import.
**Proposed fix:** Resolve both paths strictly and compare path components: `resolved_server = Path(resolved).resolve(strict=True)`, `canonical_site = Path(site_packages).resolve(strict=True)`, then require `resolved_server.is_relative_to(canonical_site)` (or `relative_to` for the supported Python floor). Report both lexical and canonical paths on failure. This preserves correct case behavior on each host and rejects sibling-prefix and symlink escapes.
**Regression-guard:** Add focused cases for an ordinary contained module, a `site-packages-shadow` sibling, and a POSIX symlink below `site-packages` targeting the checkout (skip only the symlink case where the platform cannot create it).
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

## What was done well

- `request.app.state.config.application_paths` is now the production dependency for every changed notebook route, registry repair, preview/detail read, per-notebook retrieval open/freshness check, and MCP notebook/corpus resource; the isolated-router fallbacks remain test-only compatibility seams rather than mutable process-global rebinding.
- The changes preserve the notebook threat boundary: slug validation still happens before path construction, `notebook_dir` still rejects a symlink at the slug name, and configured bases are resolved before containment comparison.
- The installed smoke now starts the absolute wheel entry point from a genuinely unrelated CWD, polls the real `/healthz`, POSTs through the live notebook API, and captures server output beneath the application root instead of manufacturing success from resolved strings.
- Child launch hygiene is broad and early: ambient `ARXMCP_*`, Python, dynamic-loader, `PWD`/`OLDPWD`, and virtualenv state is scrubbed, while HOME/profile, XDG, Hugging Face/Transformers, Matplotlib, and temporary directories are redirected before first import.
- The watched-tree manifest records entry type, size, nanosecond mtime, mode, and symlink target. Its unit regression demonstrably notices a CWD write, and the full check watches the checkout, venv, unrelated CWD, and temporary sandbox as distinct trust regions.
- The standalone probe invokes real production writers for retrieval cache, operator settings, and corpus-version marker state and requires the exact notebook/cache/settings/marker/log artifacts below the configured root.
- The byte-stable agent surface remains disciplined: no tool metadata, prompt breakpoint, tool-use ID, schema hash, result envelope, or snippet serialization changed; MCP resource JSON remains `sort_keys=True` and wrapped in the existing retrieved-data delimiters.
- No LaTeX/MathML/chunk semantics, embedding math, dependency, vendored code, Kùzu version/path, cloud service, or multi-host assumption changed. All roadmap prerequisites consumed here are already shipped, and the source `make up`, wheel, Docker/Compose, and per-store compatibility tests remain green.
- Test evidence is proportional for the implemented portion: all six new installed-path tests pass, the broader application-path/MCP-resource/corpus-manifest/Compose set passes with one expected skip, and the implementation's full gate reports 5,014 passed, 47 skipped, 1 xfailed with Ruff clean.

Severity counts: C0 H1 M1 L0

## Recommended rectification order

H1, M1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
