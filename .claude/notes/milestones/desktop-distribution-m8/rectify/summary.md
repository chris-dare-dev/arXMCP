# Rectify summary — desktop-distribution-m8

Critique: `.claude/notes/milestones/desktop-distribution-m8/critique/dedup.md`
(merged ids). Commit range rectified against: `b3a04fe..954ae99`.
Dispositions are written through `milestone-pipeline-findings.py set` (the sole
status writer); `findings.py gate` exits 0 with no open findings.

## Dispositions

| id | severity | disposition | detail |
|----|----------|-------------|--------|
| H1 | HIGH | fixed | platform-aware OpenMP policy; the Linux build no longer `SystemExit`s at spec-eval |
| H2 | HIGH | fixed (pre-existing) | closed by the owner's retroactive `allow_large_diff` authorization; untouched here |
| M1 | MEDIUM | fixed | AC2-B BEFORE arm now `pytest.skip`s instead of bare-returning |
| M2 | MEDIUM | fixed | golden gate asserts `torch_version` and names the toolchain in drift messages |
| M3 | MEDIUM | deferred | state bookkeeping — belongs to the main session's `checkpoint.py`, not the rectifier |
| M4 | MEDIUM | fixed | package-data guard derived across every frozen package + sibling hooks |
| M5 | MEDIUM | fixed | same defect as M1, closed by the same change |
| M6 | MEDIUM | fixed | weights-free frozen-child boot assertion added to `desktop-package-check` |
| M7 | MEDIUM | deferred | guarded by a new AST test rather than extracted (see below) |
| L1 | LOW | fixed | one `FORBIDDEN_ENV_PREFIXES` tuple across all three launch validators |
| L2 | LOW | fixed | same defect as L1, closed by the same change |
| L3 | LOW | deferred | no process-group kill on the frozen-child boot test |
| L4 | LOW | deferred | spec's "dropped nothing" guard still sums across both analyses |

No finding was invalidated; invalidation rate 0%.

## H1 — what was actually done, and where it departs from the proposed fix

The critique offered (a) a `darwin -> faiss/.dylibs/libomp.dylib,
linux -> faiss_cpu.libs/libgomp-*.so*` drop mapping, or (b) declare the whole
thing macOS-only. The owner directed a full fix. **Neither option was applied
verbatim, and (a) would have been a worse bug than the one it closed.**

On macOS the exclusion is safe *because* PyInstaller rewrites both consumers'
Mach-O load commands **and** both dylib IDs to `@rpath/libomp.dylib`, so dyld
dedupes the two copies onto torch's and faiss's is never mapped. There is no
ELF counterpart: auditwheel gives each wheel's vendored libgomp a distinct
mangled SONAME (`libgomp-<hash>.so.1`) recorded in **its own** consumer's
`DT_NEEDED`, so torch's copy cannot satisfy faiss's. Dropping faiss's Linux
copy — option (a) — would leave `_swigfaiss*.so` with an unresolvable
dependency and break FAISS at import on every Linux bundle. GNU libgomp also
carries no duplicate-runtime abort, so there is nothing to consolidate away.

What landed instead (`apps/desktop/pyinstaller/desktop_package.py`):

- `LIBOMP_POLICY` / `libomp_policy(platform)` — per-platform
  `canonical_dir` + `duplicate_dir`, the latter `None` on Linux. An unknown
  platform raises `BuildError` rather than guessing.
- `is_duplicate_libomp` / `is_canonical_libomp` take an optional `platform` and
  are **directory-exact**: only a `LIBOMP_PATTERN` filename sitting *directly*
  in the policy's directory matches. The exactness the infra critic verified is
  preserved — `torch/lib/libomp.dylib`, bare `libomp.dylib`,
  `faiss/_swigfaiss.abi3.so`, `faiss/.dylibs/libcompression.dylib` and
  `faiss/.dylibs/nested/libomp.dylib` are all spared. Only the *filename* half
  became a pattern, because auditwheel mangles the Linux name; the directory
  halves carry the exactness.
- `LIBOMP_PATTERN` (and its byte-identical `probe_entry.LIBOMP_NAME` twin) now
  admit an optional `-<hex>` suffix. The pinned negatives
  (`libompressed.dylib`, `libcompression.dylib`, `omp.dylib`) still fail.
  Over-matching only over-counts, which fails a guard loudly.
- `_require_single_libomp` is policy-driven: where a duplicate is expected
  (macOS) it still demands **exactly one** file; where none is (Linux) it
  demands at least one and **no two sharing a filename** — the ELF shape of the
  macOS hazard, so the Linux branch is guarded rather than merely permissive.

The three guards the owner asked to preserve are intact: the spec's
"dropped nothing" `SystemExit` (now conditioned on
`expects_duplicate_libomp()`, so it cannot fire spuriously where nothing is
droppable), the "dropping would leave no OpenMP collected" `SystemExit`, and
the driver's filesystem `_require_single_libomp`.

**macOS behaviour is unchanged, measured not asserted:** `make
desktop-package-check` re-ran the full two-build gate and
`test_bundle_ships_exactly_one_openmp_runtime` still finds exactly one regular
OpenMP file under `_internal/torch/lib`, with `faiss/.dylibs` gone from the
bundle entirely; `test_a_second_openmp_copy_aborts_the_frozen_process` still
reproduces the `OMP: Error #15` abort.

### What I could NOT verify from macOS — stated plainly

There is no Linux host in this session, so **no Linux `make desktop-package`
was executed.** What is verified is that the macOS path is unchanged in
behaviour and that the Linux policy resolves, is self-consistent, and no longer
hard-fails: `test_libomp_policy_resolves_on_every_supported_platform` and
`test_libomp_inventory_policy_is_platform_specific` exercise the `linux` branch
by passing `platform="linux"` explicitly, so they run on every `make test` from
any host. The claim "a Linux build now completes" rests on removing the only
macOS-literal predicate that raised, plus the auditwheel/delocate reasoning
above — not on an executed Linux build. The first real Linux build should
confirm the OpenMP inventory it produces (two files, distinct names) and, if it
differs, `LIBOMP_POLICY` is the one place to correct.

## The Linux silent pass (M1 / M5)

`test_a_second_openmp_copy_aborts_the_frozen_process` bare-`return`ed off
macOS, reporting `passed` with nothing asserted, and so routed around the
`DESKTOP_PACKAGE_GATE` zero-skip detector built to stop exactly that. It now
calls `pytest.skip()` naming the platform requirement (Mach-O install-name
rewriting; `OMP: Error #15`), which `conftest._DESKTOP_GATE_SKIPS` converts
into a **session failure** on Linux — the honest outcome when the platform
cannot produce the evidence. `pyproject.toml`'s marker text and CLAUDE.md 4.5
now say so: the *build* runs on macOS and Linux, the *gate* fails on Linux by
design.

Regression guard: `test_no_desktop_gate_test_short_circuits_with_a_bare_return`
AST-walks both gate modules and fails on any `return` in a test body (nested
helpers excluded), so this defect class cannot return to either file.

## M6 — the boot assertion belongs in the package gate, and now is there

`desktop-package-check` never reached `create_app()`; the only test booting the
frozen bundle sat behind `requires_bundled_model` (~4.6 GB of cached weights).
That is the exact blind spot that let m7 ship an unbootable bundle.
`test_frozen_child_boots_without_any_model_weights` now runs in the package
gate: an **empty** data root plus `ARXMCP_BOOTSTRAP_MODE=1` makes
`Resources.startup` return its stub before touching BGE-M3, LanceDB or the
reranker, so the cost is one process launch and no HF cache. The child emits
`Bound` only after the FastAPI lifespan and the socket bind, so the handshake
alone proves `create_app()` ran — catching a missing data file, a missing
hidden import or a broken runtime hook. `/healthz` is then asserted 200. The
real-weights warm map stays in `desktop-model-check`. Confirmed passing against
a real bundle in this run.

## M4 — derived, not hand-listed

`hook-server.py` covered `server` alone while `ingest`, `ops` and `tools` also
declare wheel package-data. The list now comes from
`[tool.setuptools.package-data]` in `pyproject.toml`:
`test_bundle_ships_every_wheel_data_file_of_every_frozen_package` iterates it
and checks **every package the bundle actually freezes** against the build
venv's installed tree, asserting `server` was among them so it cannot pass
vacuously; `test_package_data_declaration_is_readable_and_covers_server` (fast)
guards the parse itself. Sibling `hook-ingest.py` / `hook-ops.py` /
`hook-tools.py` were added so a tree that *does* get frozen brings its data
with it — each is inert when the frozen child never imports that package.

## M7 — deferred, but the risk is pinned

The spec still `exec_module`s the build driver to share one predicate between
build and test. The clean fix (a side-effect-free `libomp_policy` module) is
well past the MEDIUM budget, and the critique's cheap alternative — raise
unless imported as `__main__`/`arxmcp_desktop_package` — is incompatible with
the spec's own loader name (`arxmcp_desktop_package_spec_helpers`). Instead
`test_driver_module_body_is_declaration_only` AST-pins the driver's top level to
imports/assignments/defs plus the existing pinned-size `raise` guard, so the
named failure mode (a future module-level statement executing inside its own
build) fails a fast test rather than producing an inexplicable nested build.

## Deferred, with reasons

- **M3** — `state.json`'s frozen `milestone_brief` is the pre-revision AC set.
  Bookkeeping only; `milestone-pipeline-resolve-brief.py` reads the roadmap
  live. State writes are the main session's through `checkpoint.py`
  (one-writer rule), so the rectifier does not touch it.
- **M7** — above.
- **L3** — `_stop_process` kills the direct child only, with no process-group
  kill or orphan assertion, on the tests that drive the frozen (spawn-re-exec)
  child. m6's cleanup-evidence probes cover the class; no orphan was observed
  across the four gate runs in this session.
- **L4** — the spec's "dropped nothing" guard sums across both analyses, so a
  single-analysis regression is invisible at the spec layer.
  `_require_single_libomp` inspects the merged bundle on disk and catches the
  dangerous direction.

## Test deltas

| file | what it now guards |
|---|---|
| `tests/test_desktop_package.py` | `test_libomp_policy_resolves_on_every_supported_platform` (H1 — both platforms resolve; drop expected only where a duplicate exists; unknown platform raises) |
| `tests/test_desktop_package.py` | `test_libomp_inventory_policy_is_platform_specific` (H1 — Linux guard still rejects two same-named copies and zero copies) |
| `tests/test_desktop_package.py` | `test_no_desktop_gate_test_short_circuits_with_a_bare_return` (M1/M5) |
| `tests/test_desktop_package.py` | `test_all_three_launch_validators_forbid_the_same_environment` (L1/L2) |
| `tests/test_desktop_package.py` | `test_driver_module_body_is_declaration_only` (M7 risk pin) |
| `tests/test_desktop_package.py` | `test_package_data_declaration_is_readable_and_covers_server` + widened `test_bundle_ships_every_wheel_data_file_of_every_frozen_package` (M4) |
| `tests/test_desktop_package.py` | `test_frozen_child_boots_without_any_model_weights` (M6) |
| `tests/test_desktop_package.py` | `test_libomp_pattern_covers_the_openmp_runtime_family` extended with auditwheel-mangled names |
| `tests/test_desktop_bundled_model.py` | `torch_version` assertion + toolchain in every drift message; fixture toolchain-record pin (M2) |

## Check gate results (measured this session, not quoted)

| gate | result | baseline |
|---|---|---|
| `cargo fmt --all --manifest-path apps/desktop/Cargo.toml -- --check` | PASS (via `make desktop-conformance`) | PASS |
| `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings` | PASS (via `make desktop-conformance`) | PASS |
| `make desktop-package-check PYTHON=.venv/bin/python` | **33 passed in 290.56s** | 26 passed / 255 s (+7 new tests) |
| `make desktop-model-check PYTHON=.venv/bin/python` | **7 passed in 37.61s** | 7 passed / 177 s |
| `make desktop-conformance PYTHON=.venv/bin/python` | **42 + 30 + 33 passed** | 42 + 30 + 33 |
| `make test PYTHON=.venv/bin/python` | **5148 passed, 77 skipped, 1 xfailed in 328.85s** | 5142 / 76 / 1 |
| `ruff check .` | clean | clean |

`make test`'s deltas are exactly accounted for: +6 new fast tests, and +1 skip
from the new `requires_desktop_package`-marked boot test (marker-deselected in
the default run). No regressions.

## external_writes_required

- `git push origin main` — **NOT executed here.** The rect commit is local and
  signed; the main session gates the push with explicit user authorization.
