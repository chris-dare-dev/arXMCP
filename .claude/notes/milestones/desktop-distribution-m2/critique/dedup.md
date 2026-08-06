# Critique (merged) — desktop-distribution-m2

**Critics:** milestone-adversary-critic, milestone-arxmcp-critic
**Commit range:** 092ab7b5f6e6d30dd2b6358074d0a7b97b12d57d..3e2dd21819f7cf2ce8d5cb26934c8c59194b5253
**Diff stats:** 9 files, 952 LOC
**Critique format version:** 1.0

> **Merge note.** Each critic authored its ids from 1 within its own file, so
> they collided across files. `findings.py merge` renumbered them into one
> gapless per-severity sequence in critic dispatch order; bodies are verbatim.
> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in
> the per-critic files. Re-running merge after a critic file changes will shift
> these ids - see milestone-pipeline-critique-format.md.
>
> - `milestone-adversary-critic` (adversary.md): ids unchanged
> - `milestone-arxmcp-critic` (arxmcp.md): H1->H4, M1->M2

## Verdict

**DO-NOT-SHIP** — the most severe of the per-critic verdicts below.

### milestone-adversary-critic — DO-NOT-SHIP

DO-NOT-SHIP

Both implementation commits are unsigned, which is a repository-level contract violation. The relocation work is directionally sound, but the smoke does not observe writes beside the installed environment and does not prove that the settings sentinel was persisted; its metadata-only observer also has a reproduced equal-size-rewrite blind spot. The cumulative 952-LOC range independently trips the mandatory review-size gate.

### milestone-arxmcp-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The selected-root wiring is correct for the consumers this range changes, and the installed-wheel gate now proves substantially more than path-string resolution: it boots the installed entry point outside the checkout, performs real writes, inventories watched trees, and preserves the frozen MCP/cache surface. One HIGH remains in the installed server's ordinary UI workflow, however. The ingest child reaches `tools.notebook_ingest`, but that wrapper passes explicit notebook LanceDB/log paths while leaving ar5iv, parsed-corpus, chunk, embedding, and ops writers on import-time `REPO_ROOT/var/arxmcp` defaults. In a wheel those defaults are beside `site-packages`; the new smoke creates a notebook but never starts ingest, so both the runtime defect and the watched-venv mutation remain invisible. The second finding is confined to proof strength: the wheel-import provenance check uses a textual prefix rather than canonical path containment.

## Executive summary — milestone-adversary-critic

- [CRITICAL] Both implementation commits report `%G? = N` despite the mandatory GPG-signing rule.
- [HIGH] The cumulative implementation is 952 changed LOC, over twice the mandatory 400-LOC review limit.
- [HIGH] The smoke watches the venv but not its parent, so a write beside the installed application passes unnoticed.
- [HIGH] The settings writer is called, but the only postcondition is existence of a database the live server already created.
- [MEDIUM] The metadata-only manifests can miss an equal-size content rewrite when mtime is preserved or restored.

## Executive summary — milestone-arxmcp-critic

- [HIGH] The installed UI ingest subprocess still sends parsed HTML, chunks, embeddings, and ingest statistics to package-root defaults; the full-wheel smoke stops after notebook creation and never exercises that path.
- [MEDIUM] The wheel provenance check accepts a textual path prefix, so a sibling-prefix path or a symlink below `site-packages` can satisfy the check without the imported module being canonically contained there.
- [CLEAN] Config-owned notebook and corpus paths now reach the changed HTTP, UI, retrieval, and MCP-resource consumers while existing slug and symlink rejection remains intact.
- [CLEAN] The child environment is scrubbed before import and redirects application, HOME/XDG, model, plotting, loader, Python, and temporary state below the selected root.
- [CLEAN] `server/tools.py`, prompts, result envelopes, and schema pins are untouched; MCP resources retain deterministic JSON serialization and delimiter wrapping.
- [CLEAN] Math fidelity, no-fork, tier sequencing, loopback binding, Kùzu pin/path, and the macOS `KMP_DUPLICATE_LIB_OK` guard are unchanged.
- [CLEAN] Six new focused tests pass; the implementation records a green full wheel check and `make test` result of 5,014 passed, 47 skipped, 1 xfailed with Ruff clean.

## Findings

**C1 — Implementation commits are unsigned** (CRITICAL)

**Where:** no specific file
**Anchor:** `be709d9b3cb0bcab6dfd5f22c276e4ead64bbc01 N`
**What:** `git log --format='%H %G?'` reports `N` for both `be709d9` and `3e2dd21`, although `CLAUDE.md` requires GPG signing on every commit.
**Why it matters:** Unsigned implementation commits violate the repository's load-bearing commit-integrity contract and are a release blocker under the canonical severity rubric.
**Proposed fix:** Before any push, recreate both implementation commits with GPG signing enabled while preserving their conventional subjects and required co-author trailers, then verify every commit in the implementation range with `git verify-commit`.
**Regression-guard:** Add the implementation-range preflight `git verify-commit <sha>` for each commit and fail Phase 3 fan-in if any command exits non-zero.
**Source critic:** milestone-adversary-critic
**Source axis:** Commit hygiene

**H1 — Cumulative diff exceeds the review limit** (HIGH)

**Where:** no specific file
**Anchor:** `9 files changed, 901 insertions(+), 51 deletions(-)`
**What:** The cumulative range changes 952 LOC while `allow_large_diff` is false, exceeding the mandatory greater-than-400-LOC review threshold.
**Why it matters:** This is the rubric's defect-detection cliff: path wiring, subprocess control, filesystem observation, and 315 lines of tests are too much independent behavior for one review unit.
**Proposed fix:** Re-scope the delivery into separately dispatched, test-bearing slices under 400 changed LOC (Config consumer wiring, observer primitives, and installed-wheel orchestration), and rerun the full critique/gate cycle for each slice before integration.
**Regression-guard:** Have the pipeline compute cumulative insertions plus deletions before implementation fan-in and hard-stop above 400 LOC unless the canonical policy explicitly permits a split or continuation.
**Source critic:** milestone-adversary-critic
**Source axis:** Diff size

**H2 — Application-parent writes escape observation** (HIGH)

**Where:** `tools/wheel_install_check.py:658`
**Anchor:** `"installed environment": filesystem_metadata_manifest(venv),`
**What:** The boot smoke snapshots the venv subtree and a separate boot sandbox, but never snapshots `venv.parent`, so a runtime write such as `venv.parent / "leak.db"` changes none of the watched manifests.
**Why it matters:** The milestone explicitly requires proof that no write lands beside the installed application, and this observer permits exactly that escape while still reporting confinement success.
**Proposed fix:** Snapshot the complete wheel-check work directory (`venv.parent`) after build/install and require it to remain unchanged during boot, while retaining the separate data-root allowance only for the boot sandbox's `data/` subtree.
**Regression-guard:** Add a synthetic test that creates a sibling file beside `venv` between snapshots and asserts the application-parent guard raises `CheckFailed` naming that path.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**H3 — Settings write has no persisted-effect check** (HIGH)

**Where:** `tools/wheel_install_check.py:765`
**Anchor:** `data_dir / "cache" / "notebooks.db",`
**What:** The smoke treats `notebooks.db` existence as proof of the settings write even though server startup creates that same file before `_WRITER_PROBE` calls `set_setting`, so a no-op settings writer still passes every postcondition.
**Why it matters:** The explicit acceptance criterion requires an observed settings write beneath the root, not merely a successful function call against a pre-existing notebook database.
**Proposed fix:** Read `desktop_relocation_probe` back from `config.notebooks_db_path` with `get_setting` inside the installed probe, fail unless its value is exactly `"ok"`, and include the verified value in the structured parent report.
**Regression-guard:** Add a probe test with `set_setting` replaced by a no-op and require the persisted-effect assertion to fail even when `notebooks.db` already exists.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**H4 — Installed UI ingest still writes through package-root defaults, outside the selected data root** (HIGH)

**Where:** `tools/wheel_install_check.py:721`
**Anchor:** `            _post_smoke_notebook(port)`
**What:** The live portion of the new smoke creates a notebook and then switches to the standalone `_WRITER_PROBE`; it never POSTs `/ui/api/notebooks/{slug}/ingest`. That omitted server path spawns `sys.executable -m tools.notebook_ingest` (`server/ingest_tracker.py:232-239`). The child correctly resolves its notebook directory from `ARXMCP_DATA_DIR`, but `tools/notebook_ingest.py:107-112` passes only the notebook LanceDB and log/failure paths to `run_bulk_ingest`. The remaining defaults still come from the installed module location: `ingest/ar5iv_fetch.py:53-55` derives ar5iv and parsed roots from `REPO_ROOT`, `ingest/chunker.py:77-80` derives parsed/chunks/chunk-log roots from `REPO_ROOT`, `ingest/embedder.py:160-165` derives chunks/embeddings/stats/log roots from `REPO_ROOT`, and `ingest/store.py:125-127` derives store statistics from `REPO_ROOT`. `ingest/bulk_ingest.py:330,343,349` then calls `chunk_paper`, `embed_paper`, and `load_embed_record` without overriding those paths. In an installed wheel, these are paths beside the package in the venv rather than children of `Config.application_paths.root`; on a read-only installation ingest fails, and on this writable test venv it mutates the watched installation tree. A direct installed-mode import reproduced the split: Config selected the temporary data root while ar5iv, parsed, chunks, embeddings, embed stats, and store stats all resolved under the module checkout's `var/arxmcp` analogue.
**Why it matters:** Notebook ingest is the primary mutation launched from the loopback operator console. An installed server can pass `/healthz`, notebook creation, and every new confinement assertion yet fail its main data-producing workflow or write corpus/cache/ops state into `site-packages`. That violates the local-first single-root contract, makes uninstall/reinstall capable of discarding user state, and means the regression explicitly intended to catch repository/package-derived writable defaults has a production-sized blind spot.
**Proposed fix:** Thread the live `ApplicationPaths` corpus, cache, and ops children through `IngestTracker` → `tools.notebook_ingest` → `run_bulk_ingest` and onward into `chunk_paper`, `embed_paper`, `load_embed_record`, and store-stat writers. Preserve the existing source-mode defaults for offline CLIs, but make the server-launched child receive explicit paths (arguments or a validated absolute data-root environment) rather than rebinding mutable globals. Extend the full-wheel gate with a deterministic, network-free ingest-child probe that reaches the same server subprocess boundary and proves every produced path is beneath the selected root while the venv, checkout, and CWD manifests remain unchanged.
**Regression-guard:** `tests/test_installed_path_consumers.py::test_server_ingest_child_uses_application_paths` should launch the real child boundary with poisoned package/CWD defaults and assert parsed, chunk, embedding, store-stat, and failure/log writes land below Config; the opt-in `make wheel-check-full` should exercise the same installed child with deterministic local input.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint

**M1 — Metadata manifest misses equal-size rewrites** (MEDIUM)

**Where:** `tools/wheel_install_check.py:454`
**Anchor:** `File contents are not hashed: hashing a dependency-complete venv would`
**What:** `filesystem_metadata_manifest` records type, size, mtime, mode, and symlink target but no regular-file digest, so rewriting `AAAA` to `BBBB` and restoring the original mtime produces an identical manifest.
**Why it matters:** The before/after comparison can certify an unchanged checkout, CWD, or installed tree even though file bytes changed, weakening the smoke's no-outside-write evidence.
**Proposed fix:** Stream a content digest for regular files into each manifest entry (and include the watched root itself); if hashing the full venv is too costly, use a content-aware project-package manifest plus a platform-appropriate change-time/inode guard for the remaining dependency tree.
**Regression-guard:** Extend the manifest tests with an equal-size regular-file rewrite whose mtime is restored and assert `changed_manifest_paths` reports the file.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M2 — Wheel provenance uses textual prefixing instead of canonical containment** (MEDIUM)

**Where:** `tools/wheel_install_check.py:647`
**Anchor:** `        if not resolved.lower().startswith(site_packages.lower()):`
**What:** The claimed proof that `server.__file__` is below the fresh venv's `site-packages` lowercases two strings and compares their prefixes. This accepts a sibling such as `/venv/lib/site-packages-shadow/server/__init__.py`, and it accepts a path lexically below `site-packages` whose file or ancestor is a symlink to the checkout. Neither case is canonical containment, and string lowercasing is not the platform path model the rest of this milestone deliberately uses.
**Why it matters:** The full wheel check's later filesystem conclusions are meaningful only if the process under test actually imported the installed copy. A false provenance pass can turn the strongest pre-publish evidence into another source-checkout run, especially on a development venv containing `.pth` or symlink-based tooling. This is a test-proof weakness rather than evidence that the clean venv currently takes the wrong import.
**Proposed fix:** Resolve both paths strictly and compare path components: `resolved_server = Path(resolved).resolve(strict=True)`, `canonical_site = Path(site_packages).resolve(strict=True)`, then require `resolved_server.is_relative_to(canonical_site)` (or `relative_to` for the supported Python floor). Report both lexical and canonical paths on failure. This preserves correct case behavior on each host and rejects sibling-prefix and symlink escapes.
**Regression-guard:** Add focused cases for an ordinary contained module, a `site-packages-shadow` sibling, and a POSIX symlink below `site-packages` targeting the checkout (skip only the symlink case where the platform cannot create it).
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

## What was done well

### From milestone-adversary-critic

- The implementation threads one immutable `Config.application_paths` layout through HTTP routes, per-notebook retrieval, UI previews, and MCP resources instead of adding mutable global rebinding.
- Slug validation, symlink containment, and the existing `base=` helper seams remain in place on every changed notebook path.
- The installed child environment removes inherited arXMCP, Python, virtualenv, and dynamic-loader influence before first import and redirects known mutable library roots beneath the data root.
- The full smoke invokes the absolute wheel-installed console script from an unrelated CWD, verifies import provenance under site-packages, and polls the real `/healthz` endpoint in bootstrap mode.
- Real notebook, retrieval-cache, and corpus-marker writers are exercised, with stdout/stderr capture located beneath the canonical logs directory.
- The always-on regressions poison legacy module globals and run real writer probes from two distinct working directories.
- The focused relocation suite, the broader path/route/resource suite, Ruff, and the independently rerun canonical `make test` gate all passed (`5014 passed, 47 skipped, 1 xfailed`).
- No dependency, MCP tool schema, prompt-cache hash, roadmap progress record, or external system was mutated by the implementation range.

### From milestone-arxmcp-critic

- `request.app.state.config.application_paths` is now the production dependency for every changed notebook route, registry repair, preview/detail read, per-notebook retrieval open/freshness check, and MCP notebook/corpus resource; the isolated-router fallbacks remain test-only compatibility seams rather than mutable process-global rebinding.
- The changes preserve the notebook threat boundary: slug validation still happens before path construction, `notebook_dir` still rejects a symlink at the slug name, and configured bases are resolved before containment comparison.
- The installed smoke now starts the absolute wheel entry point from a genuinely unrelated CWD, polls the real `/healthz`, POSTs through the live notebook API, and captures server output beneath the application root instead of manufacturing success from resolved strings.
- Child launch hygiene is broad and early: ambient `ARXMCP_*`, Python, dynamic-loader, `PWD`/`OLDPWD`, and virtualenv state is scrubbed, while HOME/profile, XDG, Hugging Face/Transformers, Matplotlib, and temporary directories are redirected before first import.
- The watched-tree manifest records entry type, size, nanosecond mtime, mode, and symlink target. Its unit regression demonstrably notices a CWD write, and the full check watches the checkout, venv, unrelated CWD, and temporary sandbox as distinct trust regions.
- The standalone probe invokes real production writers for retrieval cache, operator settings, and corpus-version marker state and requires the exact notebook/cache/settings/marker/log artifacts below the configured root.
- The byte-stable agent surface remains disciplined: no tool metadata, prompt breakpoint, tool-use ID, schema hash, result envelope, or snippet serialization changed; MCP resource JSON remains `sort_keys=True` and wrapped in the existing retrieved-data delimiters.
- No LaTeX/MathML/chunk semantics, embedding math, dependency, vendored code, Kùzu version/path, cloud service, or multi-host assumption changed. All roadmap prerequisites consumed here are already shipped, and the source `make up`, wheel, Docker/Compose, and per-store compatibility tests remain green.
- Test evidence is proportional for the implemented portion: all six new installed-path tests pass, the broader application-path/MCP-resource/corpus-manifest/Compose set passes with one expected skip, and the implementation's full gate reports 5,014 passed, 47 skipped, 1 xfailed with Ruff clean.

Severity counts: C1 H4 M2 L0

## Recommended rectification order

C1, H2, H3, H1, H4, M1, M2

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
