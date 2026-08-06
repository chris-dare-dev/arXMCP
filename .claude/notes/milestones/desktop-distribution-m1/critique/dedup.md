# Critique (merged) — desktop-distribution-m1

**Critics:** milestone-adversary-critic, milestone-arxmcp-critic
**Commit range:** feb63143b081cfbd43d5d450ce198c583db77945..1b8385f
**Diff stats:** 8 files, 533 LOC
**Critique format version:** 1.0

> **Merge note.** Each critic authored its ids from 1 within its own file, so
> they collided across files. `findings.py merge` renumbered them into one
> gapless per-severity sequence in critic dispatch order; bodies are verbatim.
> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in
> the per-critic files. Re-running merge after a critic file changes will shift
> these ids - see milestone-pipeline-critique-format.md.
>
> - `milestone-adversary-critic` (adversary.md): ids unchanged
> - `milestone-arxmcp-critic` (arxmcp.md): H1->H3, H2->H4

## Verdict

**SHIP-WITH-FIXES** — the most severe of the per-critic verdicts below.

### milestone-adversary-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The resolver itself is compact and its containment checks are sound, but its Config integration breaks two supported configurations at the exact seam meant to centralize them. Installed notebook mode now fails validation, while an explicit data root in a source checkout does not govern the paths the server actually consumes. Both HIGH findings need regression tests and correction before this milestone ships.

### milestone-arxmcp-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The resolver itself is well-shaped, local, and careful about canonical containment, but both Config integration modes have reachable path-contract failures. Installed notebook startup is rejected without an explicit conflicting override, while a source launch with `ARXMCP_DATA_DIR` continues to consume corpus and cache paths outside that root.

## Executive summary — milestone-adversary-critic

- [HIGH] Installed-mode default rebinding mutates Pydantic's explicit-field set, so `ARXMCP_NOTEBOOK` is rejected as if `ARXMCP_LANCEDB_PATH` had also been supplied.
- [HIGH] In source mode, an explicit `ARXMCP_DATA_DIR` updates only `data_dir`; LanceDB, caches, notebooks, and ops remain legacy CWD-relative paths outside that root.

## Executive summary — milestone-arxmcp-critic

- [HIGH] Installed notebook Config treats resolver-derived defaults as explicit overrides and refuses startup.
- [HIGH] Source Config records `ARXMCP_DATA_DIR` but leaves live corpus, index, cache, and ops fields on legacy relative paths.
- [CLEAN] Canonicalization, lexical traversal rejection, descendant-symlink escape detection, symlink-loop handling, and EAFP preparation are sound within the documented TOCTOU boundary.
- [CLEAN] Cache-byte stability, math fidelity, and MCP 2025-06-18 wire behavior are untouched by this range.
- [CLEAN] Tier dependencies, local-only operation, the no-fork policy, canonical `index/kuzu`, and the macOS pytest guard remain intact.

## Findings

**H1 — Installed notebook mode mistakes defaults for explicit aliases** (HIGH)

**Where:** `server/config.py:585`
**Anchor:** `for path_field, config_field in config_`
**What:** Assigning every installed-mode resolved default with normal `setattr` adds those fields to `model_fields_set`, so the following notebook validator treats the default LanceDB path as an explicit override and rejects every installed `Config` with `notebook` set; the same mutation also makes the cache and BM25 defaults look explicit.
**Why it matters:** An installed desktop/server process cannot start in the supported single-notebook mode, and merely removing the immediate conflict would still suppress the per-notebook cache and BM25 isolation branches.
**Proposed fix:** Snapshot which path fields were supplied before any rebinding (or fold root resolution and notebook derivation into one validator) and have all ambiguity/isolation decisions consult that immutable input set; update the frozen `ApplicationPaths` view after notebook derivation so it matches the paths the server will use.
**Regression-guard:** Add an installed-mode test with an explicit data root, a valid notebook marker, and no per-store aliases; assert `Config` succeeds and its LanceDB, retrieval-cache, and BM25 paths are notebook-local beneath that root, while a genuinely explicit LanceDB alias still raises.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**H2 — Explicit source data root does not root server paths** (HIGH)

**Where:** `server/config.py:584`
**Anchor:** `if paths.mode != "source":`
**What:** The source-mode branch deliberately skips rebinding all compatibility fields, even when `ARXMCP_DATA_DIR` was explicitly supplied, producing a Config whose canonical `data_dir` is the requested absolute root while `lancedb_path`, `cache_db_path`, `notebooks_db_path`, and `ops_dir` remain under relative `var/arxmcp`.
**Why it matters:** Running from a checkout with `ARXMCP_DATA_DIR=/chosen/root` can still read and write corpus, cache, notebook, and ops state under the startup CWD/repository, violating the milestone's single-root and no-inconsistent-resolution criteria.
**Proposed fix:** Preserve legacy relative spellings only for the fully unset source-checkout default; when the root or a retained alias is explicitly configured, assign each Config consumer the resolver's canonical value while retaining the approved source-only external-alias compatibility behavior.
**Regression-guard:** Add a source-mode `Config` test with an explicit absolute `ARXMCP_DATA_DIR`, change CWD after construction, and assert every storage/ops field remains canonical beneath that root; add a relative source alias case that proves its captured-startup-CWD resolution is also propagated to the consuming field.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**H3 — Derived defaults masquerade as notebook overrides** (HIGH)

**Where:** `server/config.py:586`
**Anchor:** `setattr(self, config_field, getattr(paths, path_field))`
**What:** These resolver-derived assignments add defaulted `lancedb_path`, `cache_db_path`, and `bm25_index_root` to `model_fields_set`, so installed `Config` with `ARXMCP_NOTEBOOK` but no explicit per-store override is rejected as though `ARXMCP_LANCEDB_PATH` were set.
**Why it matters:** The installed notebook launch path fails during config parsing, and merely bypassing its first conflict check would still suppress the existing per-notebook cache and BM25 isolation because those derived defaults also look explicit.
**Proposed fix:** Snapshot the caller-supplied field set before assigning resolver defaults and have every later notebook conflict/isolation check consult that immutable snapshot; after notebook derivation, synchronize the canonical path view with the effective paths.
**Regression-guard:** Add `tests/test_application_paths.py::test_installed_notebook_uses_derived_paths`: create the notebook corpus marker below an installed root, set only `ARXMCP_DATA_DIR` plus `ARXMCP_NOTEBOOK`, assert Config succeeds and LanceDB/cache/BM25 are notebook-scoped, then assert a genuinely explicit `ARXMCP_LANCEDB_PATH` still conflicts.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**H4 — Source Config ignores its resolved data root** (HIGH)

**Where:** `server/config.py:584`
**Anchor:** `if paths.mode != "source":`
**What:** The source-mode branch updates `data_dir` but skips every resolver-backed consumer field, so `ARXMCP_DATA_DIR=/X` yields `application_paths.lancedb=/X/index/lancedb` while `lancedb_path`, `cache_db_path`, and their siblings remain under relative `var/arxmcp`.
**Why it matters:** A normal source-checkout launch can read or write outside the configured application root or fail against the wrong corpus, violating the milestone's single-root and no-inconsistent-resolution criteria.
**Proposed fix:** Propagate resolver paths to every non-explicit field whenever `ARXMCP_DATA_DIR` is supplied, including source mode; preserve only explicitly supplied source aliases as the ADR-approved legacy exceptions, and retain relative default spellings only when the root is entirely unset if compatibility requires them.
**Regression-guard:** Add a source-mode Config test with only `ARXMCP_DATA_DIR` set, assert every non-external storage field equals its `application_paths` counterpart and remains below the root after `chdir()`, and retain a separate test for explicit trusted source aliases.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint

## What was done well

### From milestone-adversary-critic

- `ApplicationPaths` is frozen and slotted, giving callers one immutable typed layout rather than a mutable bag of path strings.
- Resolution is side-effect-free; directory creation and the EAFP writability probe are isolated in `prepare()`.
- Canonical `resolve(strict=False)` plus `relative_to` checks correctly reject lexical traversal, descendant-symlink escape, and symlink loops in the tested cases.
- The fixed layout preserves the canonical `index/kuzu` spelling and includes corpus, index families, notebooks, caches, ops, logs, backups, and temporary state.
- Tests exercise missing roots, Unicode and whitespace, relative source roots, installed absolute roots, every retained alias, root symlinks, descendant symlinks, and loop rejection.
- The focused path/operator-settings tests and changed-file Ruff check pass, and an independent wheel-content/console-script check also passes.
- The commit carries the required co-author trailer and an embedded `gpgsig`; local trust verification was unavailable only because the sandbox could not open the user's GPG trust database.
- No new dependency, external mutation, roadmap progress edit, banned production `assert`, or `kuzudb` path drift was introduced.

### From milestone-arxmcp-critic

- `ApplicationPaths` is a frozen, slotted value object with one explicit layout covering corpus, all canonical index families, notebooks, caches, ops, logs, backup staging, and temporary state.
- Root and child resolution use `resolve(strict=False)` plus `relative_to`, correctly supporting missing roots while rejecting the tested lexical traversal, descendant-symlink escape, and symlink-loop cases.
- Resolution is side-effect-free, while `prepare()` uses directory creation plus a randomized exclusive `mkstemp` probe instead of the destructive fixed-name prototype pattern.
- Installed platform defaults are absolute and CWD-independent, source fallback remains `<repo>/var/arxmcp`, and container mode fails closed without an explicit absolute root.
- The seven retained environment aliases are centralized, strict-mode aliases are root-confined, and source-only external compatibility exceptions are surfaced deterministically in `legacy_external_aliases`.
- `_notebook_common` now derives its fixed corpus/notebook aliases from the resolver, and operator settings moved from import-bound function defaults to call-time resolution.
- The focused suite covers relative, absolute, missing, Unicode/whitespace, read-only-failure, root-symlink, descendant-symlink, loop, traversal, alias, and installed-default cases.
- The implementation records a green 5,000-test gate and preserves `KMP_DUPLICATE_LIB_OK=TRUE`; no MCP schema or prompt hash needed re-pinning.
- The dependency spike is complete, the large diff was explicitly authorized and checkpointed, the implementation commit is signed and trailered, and no fork, cloud dependency, or external mutation was introduced.

Severity counts: C0 H4 M0 L0


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **H2, H4, H1, H3** at `server/config.py:584-586` (HIGH): Explicit source data root does not root server paths; Source Config ignores its resolved data root; Installed notebook mode mistakes defaults for explicit aliases; Derived defaults masquerade as notebook overrides

## Recommended rectification order

H1, H2, H3, H4

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
