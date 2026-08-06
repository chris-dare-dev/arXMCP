# Critique — desktop-distribution-m1 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** feb63143b081cfbd43d5d450ce198c583db77945..1b8385f
**Diff stats:** 8 files, 533 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The resolver itself is compact and its containment checks are sound, but its Config integration breaks two supported configurations at the exact seam meant to centralize them. Installed notebook mode now fails validation, while an explicit data root in a source checkout does not govern the paths the server actually consumes. Both HIGH findings need regression tests and correction before this milestone ships.

## Executive summary

- [HIGH] Installed-mode default rebinding mutates Pydantic's explicit-field set, so `ARXMCP_NOTEBOOK` is rejected as if `ARXMCP_LANCEDB_PATH` had also been supplied.
- [HIGH] In source mode, an explicit `ARXMCP_DATA_DIR` updates only `data_dir`; LanceDB, caches, notebooks, and ops remain legacy CWD-relative paths outside that root.

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

## What was done well

- `ApplicationPaths` is frozen and slotted, giving callers one immutable typed layout rather than a mutable bag of path strings.
- Resolution is side-effect-free; directory creation and the EAFP writability probe are isolated in `prepare()`.
- Canonical `resolve(strict=False)` plus `relative_to` checks correctly reject lexical traversal, descendant-symlink escape, and symlink loops in the tested cases.
- The fixed layout preserves the canonical `index/kuzu` spelling and includes corpus, index families, notebooks, caches, ops, logs, backups, and temporary state.
- Tests exercise missing roots, Unicode and whitespace, relative source roots, installed absolute roots, every retained alias, root symlinks, descendant symlinks, and loop rejection.
- The focused path/operator-settings tests and changed-file Ruff check pass, and an independent wheel-content/console-script check also passes.
- The commit carries the required co-author trailer and an embedded `gpgsig`; local trust verification was unavailable only because the sandbox could not open the user's GPG trust database.
- No new dependency, external mutation, roadmap progress edit, banned production `assert`, or `kuzudb` path drift was introduced.

Severity counts: C0 H2 M0 L0

## Recommended rectification order

1. H1
2. H2
