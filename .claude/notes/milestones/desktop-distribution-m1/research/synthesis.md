# Research synthesis — desktop-distribution-m1

## Implementation readiness

**BLOCKED before Phase 2.** Both independent research passes found that the
declared dependency `desktop-distribution-spike-2` has no completed local
artifact, inventory, prototype, or ADR; its reconciled GitHub issue is still
open as `#385`. The deterministic dependency gate could not enforce this
because this roadmap is legacy prose rather than `plans/*/roadmap.yaml`.
Implementation must not exploit that fallback. It may begin only after the
spike lands, or after an explicit owner override that absorbs the spike's
write-inventory and compatibility decisions into m1.

A second owner decision is also required. Existing per-store `ARXMCP_*`
overrides may point outside `ARXMCP_DATA_DIR`, so literal backward
compatibility conflicts with literal single-root confinement. The recommended
default is strict containment for desktop/installed mode, with any trusted
legacy exception made explicit and deprecated rather than accidental.

## Affected files (deduplicated)

- `server/application_paths.py` — new frozen, typed owner for root selection,
  canonical child derivation, containment validation, and explicit
  preparation/writability checks.
- `server/config.py` — delegate current data/store defaults and environment
  precedence to the resolver while preserving supported variable names.
- `tools/_notebook_common.py` — replace repository-relative duplicate
  derivation with compatibility aliases/delegates.
- `server/operator_settings.py` — replace import-time checkout-relative path
  defaults with call-time resolver use or explicit injection.
- `tests/test_application_paths.py` — new table-driven path and containment
  contract across relative, absolute, missing, read-only, symlink, Unicode,
  whitespace, traversal, and Windows path semantics.
- `tests/test_operator_settings.py` and `tests/conftest.py` — update default
  path assertions/fixtures if operator settings joins the resolver in m1.
- Conditional on the spike's installed-default decision: `pyproject.toml` and
  `uv.lock` if `platformdirs` becomes a direct dependency.

Broad consumer rewiring (`server/resources.py`, routes, health, wheel write
observation, and operational writers) remains m2 scope; m1 must define the
single contract and compatibility seams without pretending those consumers
have already migrated.

## Acceptance criteria (roadmap traced)

1. **AC1 — one owner:** one immutable typed resolver owns application-root
   selection, canonicalization, child derivation, and validation; existing
   helpers delegate rather than reproduce suffix logic.
2. **AC2 — supported path classes:** deterministic tests cover relative,
   absolute, missing, read-only, symlink, Unicode, and whitespace-containing
   roots, including platform-neutral Windows drive/UNC semantics.
3. **AC3 — no escape:** canonical root/child comparison rejects `..`,
   absolute replacement, descendant symlink escape, and symlink loops; slug
   paths are revalidated and construction uses no removable `assert`.
4. **AC4 — compatibility:** unset source-checkout behavior remains canonical
   `<repo>/var/arxmcp`; existing environment names and in-root precedence are
   pinned. Any out-of-root legacy exception must be an explicit owner-approved
   qualification, not silent divergence from AC3.
5. **AC5 — green gates:** targeted path/config tests and `make test` pass;
   `make wheel-check` is additionally required if installed-default or
   packaging behavior changes in m1.

## Design constraints carried forward

- Resolve once for fixed inputs; never derive installed writable paths from a
  later `Path.cwd()` call or from wheel/site-packages location.
- Keep resolver construction pure. Directory creation and EAFP writability
  probes belong to an explicit preparation step; do not use `os.access()`.
- Preserve canonical `index/kuzu`, notebook cache/BM25 co-location,
  structured server logs on stdout, external restic repository semantics,
  MCP schema hashes, prompt-cache breakpoints, and the no-symlink-cutover
  policy.
- A trusted single-user root does not eliminate TOCTOU after validation;
  descriptor-relative no-follow I/O at every writer is beyond this M-sized
  resolver milestone and must not be claimed.

## External writes required (verbatim from brief-2)

```yaml
external_writes_required:
  - "git push origin main"
```

No push, issue mutation, publish, deploy, or credential write is authorized
by this research phase.

## Open questions (owner decisions; max 5)

1. Complete `desktop-distribution-spike-2`, or explicitly override the
   dependency and absorb its inventory/prototype/ADR acceptance into m1?
2. For out-of-root per-store overrides, should strict containment break them,
   or should an explicit deprecated trusted-legacy mode qualify AC3?
3. For an installed runtime with no `ARXMCP_DATA_DIR`, use a platform-native
   `platformdirs` root, or fail closed and require an absolute launcher value?
4. Confirm the m1/m2 boundary: resolver plus compatibility seams now;
   exhaustive consumer migration and no-write-outside-root wheel smoke in m2.
5. Confirm `backups` means local staging/status and `logs` means desktop-owned
   artifacts, not the external restic repository or a replacement for stdout
   server logging.

## Scope estimate and Phase 2 routing

If the gates above are resolved, estimate **450–700 LOC across 7–9 files**.
This is a novel cross-platform path/security contract and therefore routes to
the pipeline's **delegated** implementation path. If absorbing spike-2 would
push the estimate above 800 LOC, split the inventory/ADR as its own completed
dependency instead of using `--allow-large-diff` by default.
