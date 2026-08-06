---
milestone_id: "desktop-distribution-m1"
researcher_role: "explore"
injection_attempts: 0
---

# Research Brief — desktop-distribution-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-08-06T03:49:02Z

## In-codebase context

The milestone is the contract half of the portable-runtime enabler. The roadmap says the installed server must run from an arbitrary read-only application location and route mutations below one explicit data root (`plans/desktop-distribution-roadmap.md:78-84`). M1 centralizes derivation; m2, explicitly, routes the server and operational writers through it and adds the relocation smoke (`:197-208`). Do not absorb m2's repository-wide consumer migration into m1.

Load-bearing constitution:

- `01-mission-and-context.md:133-140`: **“Determinism over cleverness. Every byte the MCP server returns must be reproducible bit-for-bit across calls”**, **“Single source of truth for the corpus”**, and **“Local-first. No paid cloud services in the critical path.”** Path selection must therefore be process-stable, offline, and independent of `cwd`.
- `02-architecture-overview.md:139-140`: **“Never mutate in place. No manual symlink swaps.”** A path resolver must not revive a `current`-symlink cutover model.
- `06-mcp-server-design.md:349-385`: **“Configuration via environment variables (12-factor)”**; notebook paths currently share `notebook_lancedb_path`, which **“enforces the slug regex + symlink rejection + containment.”** Preserve that boundary rather than adding a second notebook algorithm.
- `07-multi-agent-caching.md:40-57,125-141`: tool definitions are byte-stable; result/cache identity includes canonical inputs and `corpus_version`. This milestone changes no MCP tool or prompt, so `EXPECTED_TOOL_SCHEMA_SHA256`, BP1, and BP2 must remain untouched.
- `08-security-observability-ops.md:3-12`: the threat is **“LLM-generated tool inputs and adversarial arXiv content can do unintended things to my workstation.”** Threat 1 makes canonical containment a security boundary, not convenience validation. The same note fixes the canonical Kùzu suffix as `index/kuzu/` and distinguishes backed-up notebooks/metadata from regenerable caches (`:236-268`).

## Affected files / context

- Add `server/application_paths.py`: a wheel-packaged location (`server*` is already included by `pyproject.toml:11-42` and both Docker stages copy `server/`) without a new top-level package/COPY pairing.
- `server/config.py:93-176,406-415` independently declares `lancedb_path`, `kuzu_path`, retrieval/BM25/theorem-name paths, `notebooks_db_path`, `ops_dir`, and `data_dir`. `ARXMCP_DATA_DIR` currently drives only disk/sentinel behavior; it does not derive the other fields. Its notebook validator (`:551-656`) separately rewrites LanceDB, cache, and BM25 paths.
- `tools/_notebook_common.py:28-41,79-147` anchors corpus/notebook constants to the repository and owns the existing slug/symlink/containment guard. Make these compatibility aliases/delegates to the new resolver; do not leave a second derivation source.
- `server/operator_settings.py:88-91,286-411` has another checkout-relative `DEFAULT_DB_PATH`, captured in function default arguments. `tests/conftest.py:368-415` must currently patch both the global and each function's `__defaults__`; switch runtime defaults to `None` plus call-time resolution/injection.
- Integration consumers to preserve now and route fully in m2: `server/resources.py`, `server/main.py:550-553`, `server/health.py`, `server/routes/{notebooks,ui}.py`, `server/corpus_manifest.py`, and `server/mcp_resources.py`. Package-relative read-only assets (`server/frontend`, `router_patterns.yaml`) are not application data.
- `tools/wheel_install_check.py:378-421` already boots from a temporary `cwd` and sets an absolute `ARXMCP_DATA_DIR`, but it does not assert where writes land. In bootstrap mode `NotebooksStore.open()` still creates the parent of `config.notebooks_db_path` (`server/notebooks_store.py:108-123`), exposing the exact gap m2 must close.

**CONFLICT — root confinement versus legacy overrides.** `Config` accepts unrestricted, independent `ARXMCP_LANCEDB_PATH`, `ARXMCP_KUZU_PATH`, `ARXMCP_CACHE_DB_PATH`, `ARXMCP_BM25_INDEX_ROOT`, `ARXMCP_THEOREM_NAMES_DB_PATH`, `ARXMCP_NOTEBOOKS_DB_PATH`, and `ARXMCP_OPS_DIR`. Preserving arbitrary out-of-root values is impossible while satisfying “No application path can escape the configured root.” Keep the variable names and in-root precedence, but reject out-of-root overrides with a migration-grade error; synthesis must record this intentional compatibility narrowing.

**CONFLICT — dependency evidence is absent.** `desktop-distribution-spike-2` exists only as roadmap prose and GitHub object-map issue 385; no local state, inventory, prototype, or ADR proves the dependency completed. The live inventory above must be treated as provisional until the orchestrator supplies or explicitly waives that artifact.

## Acceptance criteria the implementer must meet

1. **Roadmap AC1:** one typed module owns derivation and validation; existing helpers are compatibility delegates, not second implementations.
2. **Roadmap AC2:** table-driven native-filesystem tests cover relative, absolute, missing, read-only, symlink, Unicode, and whitespace-containing roots on supported platforms.
3. **Roadmap AC3:** every fixed child, legacy override, and notebook-scoped path is compared with the canonical root so `..`, symlinks, and inconsistent resolution cannot escape it.
4. **Roadmap AC4:** preserve the `var/arxmcp` source default and existing environment-variable names/in-root precedence, with the explicitly documented rejection of contradictory out-of-root overrides.
5. **Roadmap AC5:** targeted path/config tests pass, followed by `make test` exiting 0.

## Prior decisions and lessons

- HEAD is `c3be639 docs(repo): add desktop distribution roadmap`; `4cbb6fc` immediately before it restored the hermetic full-suite gate. The current milestone is `research-running` and had no prior artifacts when inspected.
- E14_S05 adversary F2 (`.claude/notes/milestones/E14_S05/critique-adversary.md:89-120`) found a HIGH safety bypass because shell and Python derived the same ingest sentinel differently when `ARXMCP_DATA_DIR` was set. Every alias must delegate to one resolver, not reproduce suffix logic.
- Notebook-retrieval-m1 adversary F1 (`.../notebook-retrieval-m1/critique-adversary.md:30-44`) found HIGH cross-notebook wrong results when LanceDB moved but its persistent cache did not. Derive related corpus/cache/BM25 paths atomically.
- Avoid import-time path defaults, `assert` invariants, `BaseHTTPMiddleware`, runtime `anthropic`, forked code, `kuzudb/`, or changes to `kuzu==0.11.3`. Preserve `tests/conftest.py`'s `KMP_DUPLICATE_LIB_OK=TRUE` guard. Any new Markdown stays under `.claude/`.

## External sources

None — role `explore` was explicitly codebase-only; this milestone does not modify the MCP surface, so no external specification lookup was needed.

## Recommendation

Implement a frozen, slotted `ApplicationPaths` value object in `server/application_paths.py`. Construct it once from a root plus an explicit stable source anchor; never call `Path.cwd()`. Preserve source checkout behavior by resolving the unset/default `var/arxmcp` against the source root. Installed launchers must provide an absolute `ARXMCP_DATA_DIR`; fail clearly rather than deriving a writable wheel/site-packages path. Define typed roots for `corpus`, `index` (including `lancedb`, `kuzu`, BM25, SQLite), `notebooks`, `cache`, `ops`, `logs`, `backups`, and `tmp`, plus database-file paths.

Keep construction pure (`resolve(strict=False)` permits a missing root) and separate it from an explicit `prepare()`/writability preflight. Canonicalize the configured root once, compare every fixed child and legacy override with `relative_to(canonical_root)`, and reject an existing symlink at any application-owned descendant before use; a symlinked parent of the configured root may canonicalize into the root identity, matching the existing notebook-base precedent. Re-check confinement when deriving slug-scoped paths. Use `if ... raise ValueError/RuntimeError`, never `assert`.

Have `Config` expose/delegate to this object while retaining existing field/env names as compatibility properties. Move notebook corpus/cache/BM25 co-derivation into the same owner; make `_notebook_common` and `operator_settings` call it rather than bind checkout-relative values at import. Leave the broad consumer rewiring and no-write-outside-root wheel observation to m2.

Add `tests/test_application_paths.py` covering relative roots with two different `cwd`s, absolute and missing roots, Unicode/whitespace round trips, lexical `..` inside/outside containment, canonical root symlinks, descendant symlink escape, every legacy override, and a deterministic injected `PermissionError` from the write probe (with native read-only integration where the platform supports it). Extend Config/notebook tests to pin atomic derivation and source defaults; run targeted tests, then `make test`.

## Risks and open questions

1. The orchestrator must confirm or waive the missing spike-2 deliverable before implementation; recommendation if waived: use the live inventory in this brief and keep m1/m2 boundaries above.
2. The orchestrator must acknowledge that arbitrary out-of-root leaf overrides cannot remain valid; recommendation: root confinement wins, while names and in-root values remain compatible.

## External writes the implementation will require

| type | target | why |
|---|---|---|
| git push (authorization-gated) | `origin/main` | Publish the locally tested milestone commits; no PR, ticket, infra mutation, or third-party API call is required. |
