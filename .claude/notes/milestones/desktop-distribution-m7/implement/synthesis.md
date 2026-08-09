# Implement synthesis — desktop-distribution-m7

## Built

- **AC1 — deterministic onedir, CLOSED exception set of size 0 (measured).**
  `make desktop-package` builds from the committed spec
  (`apps/desktop/pyinstaller/arxmcp_desktop.spec`) via the driver
  (`apps/desktop/pyinstaller/desktop_package.py`). Two independent PyInstaller
  invocations (fresh `--workpath`/`--distpath` each, under gitignored
  `var/desktop-package/` — never the colliding repo-root `build/` default)
  produced **byte-identical manifests across all 6,326 entries**
  (`report.json`: `differing: []`). `NONDETERMINISTIC_EXCEPTIONS =
  frozenset()` / `EXPECTED_EXCEPTION_COUNT = 0`
  (`desktop_package.py:46-54`), double-entry-pinned in
  `tests/test_desktop_package.py:31-37` and enforced by
  `test_exception_set_is_closed_and_size_pinned` (fast, every `make test`) +
  `test_two_builds_are_byte_identical_within_pinned_exceptions` (gate); any
  NEW diverging path fails with the offending paths named.

  **Measured determinism exception set and why it is empty.** The raw
  toolchain is NOT deterministic; two real drifts were observed and
  normalized in the committed spec rather than excused:
  1. `_internal/base_library.zip` — identical 155 members and identical
     per-member bytes, but member ORDER diverged at index 142
     (`re/_parser.pyc` vs `locale.pyc`): the write order follows the module
     graph's run-to-run enumeration. Fixed by sorting the TOC in the spec's
     `_deterministic_base_library_zip` wrapper (the zip is written inside
     `Analysis()`, unreachable by post-processing) — functionally neutral,
     zipimport is name-keyed.
  2. `arxmcp-desktop-child` (the executable) — intermittently byte-different
     via the same enumeration drift in its embedded PYZ TOC. Fixed by
     `analysis.pure.sort()` before `PYZ()` for both EXEs.
  Everything else PyInstaller already normalizes (co_filename stripped, .pyc
  headers zeroed hash-based, zip dates fixed at 1980-01-01, macOS ad-hoc
  signature content-derived), verified by the empty diff. Claim scope: this
  commit, this host/toolchain (PyInstaller 6.21.0, Python 3.12.13, macOS
  arm64) — not cross-machine.

- **AC2 — frozen latex2mathml byte-parity.** `hook-latex2mathml.py`
  (`collect_data_files`) ships `unimathsymbols.txt`; a second small
  `arxmcp-desktop-probe` EXE in the SAME COLLECT (shared `_internal`)
  converts the six fixture LaTeX strings from
  `tests/test_equation_latex_route.py` inside the bundle;
  `test_frozen_latex2mathml_output_matches_source_tree` byte-compares against
  `latex2mathml.converter.convert` run in the source venv **in the same test
  invocation** (no bundle-generated golden), plus SHA-256 equality of the
  bundled vs source-tree symbol table (216,334 bytes).

- **AC3 — freeze_support, static + real-subprocess dynamic proof.**
  `server/desktop_child.py:389-395`: `multiprocessing.freeze_support()` is
  the first statement of the `__main__` guard (sole `server/**` change; AST
  regression `test_freeze_support_is_first_statement_of_main_guard` runs in
  every `make test`). Dynamic proof
  (`test_frozen_spawn_reexec_never_reenters_main`) launches the REAL frozen
  executable twice — deliberately NOT the repo's hollow-mock precedent
  (`test_desktop_sidecar_spike.py:83-90`): the control arm proves entering
  `main()` is observable on this binary (traceback frame `", in main"`); the
  `--multiprocessing-fork pipe_handle=<fd>` arm (real inherited pipe, write
  end closed) must show `pyi_rth_multiprocessing._freeze_support →
  spawn_main → EOFError` and NO `in main` frame. main() ignores argv, so
  without the guard both arms would behave identically — the divergence IS
  the guard working.

- **AC4 — direct_url.json.** The leak is REPRODUCED on the real toolchain
  every provisioning (`--force-reinstall` regenerates it;
  `leak_observed: True` asserted by `test_no_direct_url_leak_in_bundle` so an
  absent-for-unrelated-reasons pass is impossible), then deleted pre-freeze
  (`sanitize_direct_url`); the test also walks the bundle asserting zero
  `direct_url.json` files shipped.

- **AC5 — recursive build-root scan, including compressed .pyc bytes.**
  `scan_tree` byte-scans every regular file (chunked with needle-overlap;
  per-file read-bytes == lstat-size tripwire, aggregate equality asserted),
  descends into `*.zip` members, and — via `scan_embedded.py` under the build
  venv's PyInstaller readers — decompresses both executables' embedded PYZ
  entries (8,511 module pycs), where a raw grep is blind. Needles: `$HOME`,
  username, realpath'd temp root. **This caught a real leak:**
  `_sysconfigdata__darwin_darwin` carried 21 `build_time_vars` values with
  the uv interpreter's `$HOME` path into the PYZ. Fixed in the spec
  (`_sanitize_sysconfigdata`): sanitized source recompiled into PyInstaller's
  `CONF['code_cache']` (TOC-repoint alone is a no-op — PYZ reads code objects
  pre-compiled during Analysis) with placeholder prefix
  `/arxmcp-frozen-placeholder`. Final scan: **zero hits** over 5,282 files /
  758,980,160 bytes + 155 zip members + 8,532 embedded entries. Coverage
  floors asserted (≥4,000 files, ≥100 native, ≥100 zip pycs, ≥5,000 embedded
  pycs).

- **AC6 — gates.** See gate results below; `make test` exits 0;
  `make desktop-conformance` fails on ONE pre-existing environmental test,
  reproduced identically at BASE_SHA (evidence below).

- **Runtime budget honored (m6 findings.json:240 precedent).** New marker
  `requires_desktop_package` registered in `pyproject.toml` AND
  `tests/conftest.py::_OPT_IN_MARKERS`; CLAUDE.md §4.5 count/enumeration
  updated (enforced by `test_marker_doc_consistency.py`). The expensive
  evidence lives ONLY behind `make desktop-package-check`, which sets
  `DESKTOP_PACKAGE_GATE=1` — added to `_DESKTOP_GATE_ENV`, so any skip FAILS
  the session; a missing `uv` RAISES. `make test` gains ~0.2 s of fast tests.

## Branching note

All commits on `main` in the main checkout, per repo CLAUDE.md §4.1
(single-user, all work lands on `main` directly) and the dispatch (no
worktree). A throwaway worktree at BASE_SHA was used ONLY to reproduce the
pre-existing conformance failure, then removed.

## PyInstaller provisioning (settled design, MinerU precedent)

PyInstaller never enters `pyproject.toml`/`uv.lock`. The driver provisions
`var/desktop-package/build-venv` (override: `DESKTOP_BUILD_VENV`, deliberately
not `ARXMCP_`-prefixed — unknown-var scan trap): `uv sync --locked --no-dev
--no-install-project` → freshly built wheel `--no-deps --force-reinstall` →
`uv pip install --require-hashes -r requirements-build.txt`. The hashed
lockfile pins PyInstaller 6.21.0 / hooks-contrib 2026.6 with full transitive
hashes; the wheel hashes match spike-1's recorded pins exactly (`327d1323…`,
`fd13b8ac…`). Regeneration procedure documented in `requirements-build.in`
and `docs/releasing.md` step 3.

## Files touched

- `server/desktop_child.py` — `import multiprocessing` + guard-first
  `freeze_support()` (AC3; only server/ change)
- `apps/desktop/pyinstaller/arxmcp_desktop.spec` — committed spec: wheel-
  installed entry, probe EXE, determinism normalizations, sysconfigdata
  sanitizer
- `apps/desktop/pyinstaller/desktop_package.py` — build driver: provisioning,
  sanitizer, builds, manifests, scanner, closed exception set
- `apps/desktop/pyinstaller/scan_embedded.py` — embedded CArchive/PYZ scanner
  (runs under the build venv)
- `apps/desktop/pyinstaller/hook-latex2mathml.py` — data hook (AC2)
- `apps/desktop/pyinstaller/probe_entry.py` — frozen conversion probe (AC2)
- `apps/desktop/pyinstaller/requirements-build.{in,txt}` — hash-pinned build
  stack (outside uv.lock)
- `tests/test_desktop_package.py` — 7 fast + 6 gate tests (AC1–AC5)
- `tests/conftest.py` — marker in `_OPT_IN_MARKERS`; `DESKTOP_PACKAGE_GATE`
  in `_DESKTOP_GATE_ENV`
- `pyproject.toml` — `requires_desktop_package` marker registration ONLY (no
  dependency-set change; wheel contents untouched — all new build code lives
  outside the packaged trees)
- `CLAUDE.md` — §4.5 marker count ("Eleven") + enumeration
- `Makefile` — `desktop-package`, `desktop-package-check` targets + help
- `docs/releasing.md` — checklist step 3 (desktop bundle), steps renumbered
- `.claude/notes/milestones/desktop-distribution-m7/implement/{synthesis,scope-exceeded}.md`

## Measurements

- Warm PyInstaller build: **52.2 s** per invocation on this host (spike-1
  cold baseline 74.04 s); warm re-provision 0.9 s; full-tree scan 1.8 s.
- Artifact: **5,282 regular files, 758,980,160 bytes (~759 MB)**, manifest
  6,326 entries (files+dirs+symlinks); two executables
  (`arxmcp-desktop-child`, `arxmcp-desktop-probe`), ad-hoc signed,
  `codesign --verify --strict` PASS.
- `make desktop-package-check` (2 builds + all evidence): **13 passed, 0
  skipped, 106.6 s** warm. One-time cold provisioning adds multi-minute uv
  resolution + PyInstaller download.

## Deferred

- **Frozen `executable_identity()` is broken** (discovered by AC3's control
  arm): `server/desktop_child.py:106` hashes `Path(__file__)`, which does not
  exist inside a frozen bundle (`_internal/desktop_child.py` →
  FileNotFoundError before the launch frame is read). The frozen child
  cannot complete a real supervisor handshake until identity self-measure is
  frozen-aware. Out of m7 scope (server/** frozen to the freeze_support
  change; touches the m5 supervisor contract) — this is m8+/follow-up work
  and is exactly the kind of gap the milestone said later work consumes the
  artifact to find.
- Cross-machine / cross-toolchain reproducibility: not claimed, not measured.
- OpenMP consolidation, real-model exercise in the bundle: m8 scope.

## external_writes_required

- `git push origin main` (per-event authorization; carried from research)

## Test deltas

- NEW `tests/test_desktop_package.py` — 7 fast (AST freeze_support guard,
  exception-set double-pin, scanner needle/zip/chunk-boundary units,
  sanitizer unit, manifest-diff unit) + 6 `requires_desktop_package` gate
  tests (AC1, AC2, AC3, AC4, AC5, artifact/signature).
- `tests/conftest.py` — marker deselection + zero-skip gate wiring.

## Check gate results

- `cargo fmt --all --check`: PASS
- `cargo clippy --workspace --all-targets --all-features -D warnings`: PASS
- `cargo test --workspace` (inside conformance run): 20 passed (0+8+12)
- `make test`: **PASS exit 0** — 5,129 passed / 68 skipped / 1 xfailed in
  310.3 s (baseline 5,122/62/1 + 7 new fast passes + 6 new opt-in skips;
  zero regressions), `ruff check .` clean
- `make desktop-package-check`: **PASS exit 0** — 13 passed, 0 skipped
- `make desktop-conformance`: **FAIL — pre-existing, environmental, NOT this
  diff.** `test_desktop_child.py::test_supervisor_owns_a_native_window_while_running`
  fails ("supervisor owns 0 native windows; probe is NOT blind — control pid
  re-counted ≥1"). Reproduced 3× in this session AND **identically at
  BASE_SHA `81d04ec` in a clean worktree with the same binaries**; `git diff
  BASE -- tests/test_desktop_child.py apps/desktop` is empty, so this diff
  cannot cause it. The suites before the failure are green (contract 42
  passed, child 28/29; support-floor line unreached because make aborts).
  GUI session is live (frontmost app observable); the supervisor's Tauri
  window is not AX-visible within the test's 15 s window in the current
  desktop-session state. Needs an operator-present desktop session to
  re-verify; flagged, not papered over.
- `git status`: clean except (a) `.claude/notes/milestones/desktop-distribution-m7/state.json`
  (orchestrator-owned, concurrent) and (b) untracked `build/` (owned by the
  concurrent `.gitignore` session; never written by this milestone).

## Deviations from dispatch

- Co-author trailer names the actual authoring model (repo CLAUDE.md §4.3
  "naming the actual authoring model is mandatory") rather than the
  dispatch's literal example string.
