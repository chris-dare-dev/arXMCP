# Rectify summary — desktop-distribution-m7

Critique: `.claude/notes/milestones/desktop-distribution-m7/critique/dedup.md`
(MERGED ids). Critics: `milestone-adversary-critic`,
`milestone-infra-safety-critic`. Severity counts C0 H3 M9 L3.

**Outcome: 14 fixed, 1 deferred, 0 invalidated, 0 handed back.** All three HIGH
findings were re-verified against live code before fixing — every anchor still
matched and every defect was real, so the invalidation rate is 0%.

## H1 — shared PyInstaller bincache (fixed)

`_tool_env()` now takes a `config_dir` and sets `PYINSTALLER_CONFIG_DIR`;
`build_bundle` passes `config_dir_for(workpath)` = `<workpath>/pyi-conf`, and
`build_bundle` rmtrees the workpath, so **every build starts with a cold
bincache**. The override is verified, not assumed: PyInstaller 6.21.0's
`configure.py::_get_pyinstaller_cache_dir` reads that variable ahead of the
`~/Library/Application Support` default.

`verify_determinism` records `config_dirs`, `config_dirs_distinct` and
`config_dir_b_cold` into `report.json`, and
`test_two_builds_are_byte_identical_within_pinned_exceptions` asserts all three
— a regression that re-shares the cache now fails the gate instead of quietly
re-earning a hollow "identical".

### Re-measured exception set — reported as measured, not as wanted

Two builds with distinct cold config dirs, `make desktop-package-check`,
2026-08-09:

| quantity | value |
|---|---|
| `manifest_entries` | **6326** |
| `differing` | **`[]`** |
| `identical` | `True` |
| `NONDETERMINISTIC_EXCEPTIONS` / `EXPECTED_EXCEPTION_COUNT` | `frozenset()` / `0` (unchanged) |
| `config_dirs_distinct` / `config_dir_b_cold` | `True` / `True` |
| `native_files` scanned in the bundle | 176 |

**The exception set is still EMPTY, and it is now earned.** The critique's
concern was that the 176 native binaries were cache replays; with build B cold
they were re-processed and re-signed from scratch and still hashed identically,
so no entry had to be added and the pinned count stays 0.

Independent corroboration that no cache was shared: the user-level bincache
`~/Library/Application Support/pyinstaller` holds 180 files and **zero have an
mtime inside this run's window** (`find -newermt <run start>` -> 0), where the
pre-fix build necessarily read and wrote it.

## H2 — the bundle that could not launch (fixed, not documented away)

Fixed the bug rather than papering over it, because m8 needs a bootable bundle.
`server/desktop_child.py` gains `identity_source_path()`: frozen
(`sys.frozen`) it returns `Path(sys.executable)`, else `Path(__file__)`.
Hashing the executable's own bytes is the closer analogue to the fixture
sidecar's `current_executable_sha256()` **and** to what the supervisor already
does — `lifecycle.rs::cycle` hashes `plan.identity_file` — so the two sides now
agree by construction.

Evidence on the real frozen binary: the AC3 control arm now exits **rc=2** with
`desktop child rejected launch` on stderr, i.e. the frozen child gets past
`executable_identity()` and reaches the launch-frame contract check. Pre-fix it
died inside `executable_identity()` hashing a PYZ-internal `__file__`. A fast
unit guard (`test_identity_digest_targets_the_executable_when_frozen`) pins
both branches.

`docs/releasing.md` step 3 no longer implies anything untrue; it gains a
**Supervisor wiring** note that the plan's `identity_file` must point at the
frozen executable, not at `server/desktop_child.py` — the foot-gun the fix
creates.

## H3 — the temp-root needle that could never match (fixed + demonstrated)

`default_needles()` emits the raw `tempfile.gettempdir()` as `tmp` and, when it
differs, `os.path.realpath(...)` as `tmp_real` (same treatment for `$HOME` ->
`home_real`).

**Planted-string demonstration** — a file containing only the raw temp root,
scanned with the pre-fix needle set (reproduced verbatim from the parent
commit) and with the post-fix set:

```
raw : /var/folders/dd/l249czh14l5dv27rs18y311w0000gn/T
real: /private/var/folders/dd/l249czh14l5dv27rs18y311w0000gn/T
divergent: True
pre-fix  needles: ['home', 'tmp', 'user']              PRE-FIX  hits: {}
post-fix needles: ['home', 'tmp', 'tmp_real', 'user']  POST-FIX hits: {'planted.pyc': ['tmp']}
```

The axis was inert and now fires.
`test_default_needles_cover_raw_and_realpath_temp_root` plants the same string
as a permanent guard.

## Dispositions

| id | sev | disposition | detail |
|---|---|---|---|
| H1 | HIGH | fixed | per-build `PYINSTALLER_CONFIG_DIR`; set re-measured EMPTY with B cold |
| H2 | HIGH | fixed | `identity_source_path()` hashes `sys.executable` when frozen |
| H3 | HIGH | fixed | raw + realpath temp/home needles; planted-string proof above |
| M1 | MED | fixed | `test_verify_cli_exit_codes` covers all three `main(["verify"])` exits |
| M2 | MED | fixed | mode leg split behind `skipif(win32)`; content/membership stays unguarded |
| M3 | MED | fixed | `_entered_main()` marker set survives the H2 fix; both arms use it |
| M4 | MED | fixed | footprint restated as persistent + split; `make desktop-package-clean` added |
| M5 | MED | fixed | `_require_scan_coverage` raises on a vacuous scan, in the driver |
| M6 | MED | fixed | `try`/`finally` per build + `_sweep_transient()` startup sweep |
| M7 | MED | fixed | macOS/Linux-only scope stated in five operator-facing places |
| M8 | MED | fixed | proxy/CA env passthrough + "needs network on first run" documented |
| M9 | MED | fixed | `build_paths` needles (repo root, workpaths, distpaths), prefix-deduped |
| L1 | LOW | fixed | same needle change; doc strings and code now agree |
| L3 | LOW | fixed | module-level `raise` binds the exception-set size to its pinned count |
| L2 | LOW | **deferred** | raising from `verify_determinism` would abort the module-scoped `packaged` fixture before any AC test reports, collapsing five itemised gate failures into one fixture error. Both callers check today; revisit if a third appears. |

Invalidated: none. Handed back: none.

## Regression guards added

- `tests/test_desktop_package.py::test_two_builds_are_byte_identical_within_pinned_exceptions` — H1 (config dirs distinct + B cold)
- `tests/test_desktop_package.py::test_default_needles_cover_raw_and_realpath_temp_root` — H3
- `tests/test_desktop_package.py::test_default_needles_add_uncovered_build_paths` — M9 / L1
- `tests/test_desktop_package.py::test_build_once_fails_closed_on_vacuous_scan_coverage` — M5
- `tests/test_desktop_package.py::test_verify_cli_exit_codes` — M1
- `tests/test_desktop_package.py::test_manifest_diff_catches_mode` (+ `..._content_and_membership`) — M2
- `tests/test_desktop_package.py::test_frozen_spawn_reexec_never_reenters_main` — H2 dynamic (rc=2 + rejected-launch) and M3
- `tests/test_desktop_child.py::test_identity_digest_targets_the_executable_when_frozen` — H2 unit

## Gate results (measured this run, `PYTHON=.venv/bin/python`)

| gate | result |
|---|---|
| `make desktop-package-check` | **18 passed, exit 0, 135.42 s** (zero skips). Report: 6326 manifest entries, 0 differing; scan 5282 files / 176 native / 155 zip `.pyc` / 8511 embedded-PYZ `.pyc` entries; `bytes_scanned == lstat_bytes`; zero hits |
| `make test` | **5135 passed, 68 skipped, 1 xfailed, exit 0, 380.68 s** (baseline 5129/68/1; +6 = the new tests) |
| `make desktop-conformance` | **exit 0, zero skips: 42 + 30 + 33** (baseline 42 + 29 + 33; +1 = the new frozen-identity test) |
| `cargo fmt --all -- --check` | clean |
| `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings` | clean |
| `ruff check .` | All checks passed |

No Rust source was touched; the two cargo gates are regression checks only.

## external_writes_required

- `git push origin main` — **NOT executed here.** The rect commit is local; the
  main session gates the push with explicit user authorization.
