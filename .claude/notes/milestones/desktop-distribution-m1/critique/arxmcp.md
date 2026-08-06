# Critique — desktop-distribution-m1 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** feb63143b081cfbd43d5d450ce198c583db77945..1b8385f
**Diff stats:** 8 files, 533 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The resolver itself is well-shaped, local, and careful about canonical containment, but both Config integration modes have reachable path-contract failures. Installed notebook startup is rejected without an explicit conflicting override, while a source launch with `ARXMCP_DATA_DIR` continues to consume corpus and cache paths outside that root.

## Executive summary

- [HIGH] Installed notebook Config treats resolver-derived defaults as explicit overrides and refuses startup.
- [HIGH] Source Config records `ARXMCP_DATA_DIR` but leaves live corpus, index, cache, and ops fields on legacy relative paths.
- [CLEAN] Canonicalization, lexical traversal rejection, descendant-symlink escape detection, symlink-loop handling, and EAFP preparation are sound within the documented TOCTOU boundary.
- [CLEAN] Cache-byte stability, math fidelity, and MCP 2025-06-18 wire behavior are untouched by this range.
- [CLEAN] Tier dependencies, local-only operation, the no-fork policy, canonical `index/kuzu`, and the macOS pytest guard remain intact.

## Findings

**H1 — Derived defaults masquerade as notebook overrides** (HIGH)

**Where:** `server/config.py:586`
**Anchor:** `setattr(self, config_field, getattr(paths, path_field))`
**What:** These resolver-derived assignments add defaulted `lancedb_path`, `cache_db_path`, and `bm25_index_root` to `model_fields_set`, so installed `Config` with `ARXMCP_NOTEBOOK` but no explicit per-store override is rejected as though `ARXMCP_LANCEDB_PATH` were set.
**Why it matters:** The installed notebook launch path fails during config parsing, and merely bypassing its first conflict check would still suppress the existing per-notebook cache and BM25 isolation because those derived defaults also look explicit.
**Proposed fix:** Snapshot the caller-supplied field set before assigning resolver defaults and have every later notebook conflict/isolation check consult that immutable snapshot; after notebook derivation, synchronize the canonical path view with the effective paths.
**Regression-guard:** Add `tests/test_application_paths.py::test_installed_notebook_uses_derived_paths`: create the notebook corpus marker below an installed root, set only `ARXMCP_DATA_DIR` plus `ARXMCP_NOTEBOOK`, assert Config succeeds and LanceDB/cache/BM25 are notebook-scoped, then assert a genuinely explicit `ARXMCP_LANCEDB_PATH` still conflicts.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**H2 — Source Config ignores its resolved data root** (HIGH)

**Where:** `server/config.py:584`
**Anchor:** `if paths.mode != "source":`
**What:** The source-mode branch updates `data_dir` but skips every resolver-backed consumer field, so `ARXMCP_DATA_DIR=/X` yields `application_paths.lancedb=/X/index/lancedb` while `lancedb_path`, `cache_db_path`, and their siblings remain under relative `var/arxmcp`.
**Why it matters:** A normal source-checkout launch can read or write outside the configured application root or fail against the wrong corpus, violating the milestone's single-root and no-inconsistent-resolution criteria.
**Proposed fix:** Propagate resolver paths to every non-explicit field whenever `ARXMCP_DATA_DIR` is supplied, including source mode; preserve only explicitly supplied source aliases as the ADR-approved legacy exceptions, and retain relative default spellings only when the root is entirely unset if compatibility requires them.
**Regression-guard:** Add a source-mode Config test with only `ARXMCP_DATA_DIR` set, assert every non-external storage field equals its `application_paths` counterpart and remains below the root after `chdir()`, and retain a separate test for explicit trusted source aliases.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint

## What was done well

- `ApplicationPaths` is a frozen, slotted value object with one explicit layout covering corpus, all canonical index families, notebooks, caches, ops, logs, backup staging, and temporary state.
- Root and child resolution use `resolve(strict=False)` plus `relative_to`, correctly supporting missing roots while rejecting the tested lexical traversal, descendant-symlink escape, and symlink-loop cases.
- Resolution is side-effect-free, while `prepare()` uses directory creation plus a randomized exclusive `mkstemp` probe instead of the destructive fixed-name prototype pattern.
- Installed platform defaults are absolute and CWD-independent, source fallback remains `<repo>/var/arxmcp`, and container mode fails closed without an explicit absolute root.
- The seven retained environment aliases are centralized, strict-mode aliases are root-confined, and source-only external compatibility exceptions are surfaced deterministically in `legacy_external_aliases`.
- `_notebook_common` now derives its fixed corpus/notebook aliases from the resolver, and operator settings moved from import-bound function defaults to call-time resolution.
- The focused suite covers relative, absolute, missing, Unicode/whitespace, read-only-failure, root-symlink, descendant-symlink, loop, traversal, alias, and installed-default cases.
- The implementation records a green 5,000-test gate and preserves `KMP_DUPLICATE_LIB_OK=TRUE`; no MCP schema or prompt hash needed re-pinning.
- The dependency spike is complete, the large diff was explicitly authorized and checkpointed, the implementation commit is signed and trailered, and no fork, cloud dependency, or external mutation was introduced.

Severity counts: C0 H2 M0 L0

## Recommended rectification order

H1, H2

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
