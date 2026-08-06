---
milestone_id: "desktop-distribution-m1"
researcher_role: "general"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://raw.githubusercontent.com/python/cpython/v3.11.15/Doc/library/pathlib.rst"
    sha256: "454078ed13003708a5a5f2b9046d5a434e48e5de536725ed9d3ac8d2095a64a2"
    takeaway: "Path.resolve(strict=False) canonicalizes absolute paths, resolves existing symlinks, and removes '..'; PurePath.is_relative_to is lexical and does not treat '..' specially."
  - url: "https://raw.githubusercontent.com/python/cpython/v3.11.15/Doc/library/os.rst"
    sha256: "cf14baecc0cc28937f42df24ffe9ab93984bfe82daa431206662794bdb81f94d"
    takeaway: "os.access pre-checks create a TOCTOU gap; attempt the filesystem operation and handle PermissionError instead."
  - url: "https://raw.githubusercontent.com/tox-dev/platformdirs/4.11.0/docs/platforms.rst"
    sha256: "3c6098e1c21bb6aa9a41179f45ec8dd8493dac17e5cd78c0909415d672d2021c"
    takeaway: "platformdirs 4.11.0 supplies platform-native per-user data roots for Linux, macOS, and Windows."
  - url: "https://api.github.com/repos/chris-dare-dev/arXMCP/issues/385"
    sha256: "913e9456951cff729bf04cbe715e2e5c174f7d89bb8b8c2348d9754d58ab494e"
    takeaway: "Required dependency desktop-distribution-spike-2 (#385) is still open and has not delivered its write inventory, prototype, compatibility map, or ADR."
injection_attempts: 0
---

# Research brief (general) — desktop-distribution-m1

## External sources

**Implementation is NO-GO until `desktop-distribution-spike-2` (#385) lands.** The roadmap
declares that spike a dependency and assigns it the runtime-write inventory, source/wheel/
container prototype, compatibility aliases, migration order, and GO/NO-GO ADR. The issue is
open, and there is no local milestone state, ADR, inventory, or prototype artifact. Starting
m1 now would silently make its implementer redo—and pre-empt—the dependency's decision work.

After the spike closes GO, implement one immutable typed `ApplicationPaths` resolver in an
already shipped package (prefer `server/application_paths.py`; a new top-level package would
also require `pyproject.toml` package-discovery and Docker COPY changes). It should accept
injected `environ`, startup `cwd`, and installed-default factory; resolve the root once; and
derive fixed children for corpus, index/LanceDB/BM25/Kùzu/SQLite, notebooks, cache, ops, logs,
backup staging/status, and temporary state. Keep construction side-effect-free and put
directory creation/writability probing in a separate preparation operation.

Root precedence should be:

1. Explicit `ARXMCP_DATA_DIR`; a relative value retains legacy startup-CWD meaning but is
   immediately made absolute, so later `chdir()` cannot change it.
2. When `server/__file__` has the exact source-checkout layout beside this project's
   `pyproject.toml`, use canonical `<repo>/var/arxmcp` (editable installs count as source).
3. Otherwise use `platformdirs.user_data_path("arXMCP", appauthor=False)`, independent of
   working directory. Use this one data root for all children; separate platformdirs cache
   and log roots would violate the desktop contract.

For containment, canonicalize the root and each derived path with
`Path.resolve(strict=False)`, then require `child.relative_to(root)` to succeed. This handles
missing leaves, `..`, a configured root such as macOS `/var` whose ancestors are symlinks,
and pre-existing child symlinks that escape. Never use lexical `is_relative_to()` alone.
Reject symlink loops and observed child escapes with a typed exception, not `assert`.
Writability must use EAFP (perform the create/probe and catch `PermissionError`), never
`os.access()`.

### Constitution and shipped-code constraints

- `.claude/notes/01-mission-and-context.md` requires **“Determinism over cleverness”** and
  **“Local-first.”** Resolution must therefore be pure for fixed inputs and require no
  service/network call.
- `.claude/notes/02-architecture-overview.md` says **“Never mutate in place. No manual
  symlink swaps”**; `.claude/notes/05-storage-and-indexing.md` repeats that no LanceDB
  symlinks are created or modified. The resolver validates paths; it must not introduce a
  `current` link or use a symlink as a cutover mechanism.
- `server/config.py` currently has independent defaults for LanceDB, Kùzu, retrieval cache,
  BM25, theorem-name DB, notebook DB, ops, and `data_dir`; `data_dir` does not derive them.
  Its notebook validator also preserves explicit override semantics. The spike inventory,
  not an ad-hoc grep during implementation, must be the migration checklist.
- `tools/_notebook_common.py` derives roots from `__file__` and already demonstrates resolved
  containment plus explicit notebook-symlink rejection. Centralize that policy; do not keep
  a second resolver. Its present wheel behavior points beneath the installed package and is
  the concrete bug m1/m2 must eliminate.
- Preserve canonical `index/kuzu/` and `kuzu==0.11.3`, never `kuzudb/`. Do not disturb the
  load-bearing `KMP_DUPLICATE_LIB_OK=TRUE` guard in `tests/conftest.py`.
- `.claude/notes/08-security-observability-ops.md` requires **“Structured JSON logs to
  stdout (12-factor).”** `logs_dir` is for desktop-supervisor/offline artifacts, not a silent
  server logging switch. Likewise, “backups” means local staging/status: the restic
  repository remains an operator-selected external target, never a child of the data being
  backed up.
- This milestone changes no MCP tool. Do not re-pin the tool-schema hash. It also must not
  introduce project-banned `BaseHTTPMiddleware`, runtime `anthropic`, or invariant `assert`.

### Compatibility decision required from the spike

The acceptance statements “No application path can escape the configured root” and
“Existing environment-variable values ... remain backward compatible” conflict: today an
operator may explicitly put `ARXMCP_LANCEDB_PATH`, `ARXMCP_KUZU_PATH`,
`ARXMCP_CACHE_DB_PATH`, and other per-store paths anywhere. The recommended resolution is
two explicit modes: desktop/strict mode rejects every override outside the canonical root;
legacy source/wheel mode honors an explicitly supplied per-store absolute path as a trusted,
deprecated exception while all derived paths remain contained. The spike ADR and roadmap
must state this qualification; no implementation can truthfully satisfy both literal
bullets at once.

### External writes and riskiest assumption

The only external write is `git push origin main`, performed by the orchestrator only after
per-event user authorization. Commits are local; no PR, issue mutation, package publish,
deploy, credential write, or third-party mutating API is required.

The riskiest assumption is that platform-aware defaulting plus a finite compatibility map
can preserve every launch mode without hidden write sites. That assumption is precisely
what the missing spike must test. Concrete alternative: add no `platformdirs` dependency;
make installed launchers require an absolute `ARXMCP_DATA_DIR` and fail closed when absent,
while source mode remains repo-anchored. This is simpler and stricter but is not preferred
because it changes current wheel UX and likely violates backward compatibility.

## Acceptance criteria the implementer must meet

1. Do not begin implementation until #385 closes GO with a committed write inventory,
   compatibility/migration map, and source/wheel/container evidence; implement against those
   artifacts rather than reconstructing them.
2. One immutable typed resolver owns root selection, canonicalization, child derivation, and
   validation; existing config/helpers delegate to it, with m1 versus m2 consumer-migration
   scope explicitly reconciled.
3. Source-unset behavior remains canonical `<repo>/var/arxmcp`; installed-unset behavior uses
   a platform-native absolute root and is invariant under arbitrary startup CWD and later
   `chdir()`; explicit relative values preserve documented startup-CWD compatibility.
4. All fixed derived children remain within the canonical root; tests reject `..`, absolute
   replacement, symlink escape and loop cases while accepting missing roots and exact Unicode
   and whitespace names.
5. Read-only behavior is tested through an attempted operation/`PermissionError` path (plus
   native chmod coverage where reliable), never `os.access`; Windows drive/UNC semantics get
   `PureWindowsPath` unit coverage and native supported-platform tests remain deterministic.
6. Preserve existing explicit per-store behavior under the spike's recorded compatibility
   policy, notebook cache/BM25 isolation, `index/kuzu`, stdout logging, and external restic
   repositories; no write may land beside an installed package.
7. Add/update the direct dependency and lock only if the spike confirms platformdirs, then
   pass targeted tests, `make test`, and `make wheel-check` (the latter is required for
   installed-runtime and packaging-boundary behavior even though the roadmap names only the
   former).

## Risks and open questions

1. **Blocking dependency:** #385 is open with no artifact. Owner/orchestrator must not waive
   it implicitly; either finish the spike or formally amend the dependency and absorb its AC.
2. **Contradictory compatibility AC:** choose and document the recommended strict-desktop /
   trusted-legacy-exception split, or explicitly accept a breaking removal of external
   per-store overrides.
3. **m1/m2 boundary:** m1 says one module owns every consumed root, while m2 separately owns
   routing server/notebook/retrieval/ops consumers. Keep m1 to resolver + config/default
   compatibility seams and m2 to exhaustive consumer migration, or merge/re-scope them.
4. **TOCTOU limit:** returning validated `Path` objects cannot prevent another local process
   swapping a child to a symlink before a later write. State that the root is trusted
   single-user state; a stronger guarantee requires descriptor-relative no-follow I/O at each
   write site and is not a cross-platform M-sized resolver change.
5. **Semantic roots:** confirm backup means staging/status rather than `RESTIC_REPOSITORY`,
   and logs mean desktop-owned files while server JSON stays on stdout; otherwise m1 would
   contradict the operations constitution.
