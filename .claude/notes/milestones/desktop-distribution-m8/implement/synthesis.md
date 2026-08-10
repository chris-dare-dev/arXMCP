# desktop-distribution-m8 — implementation synthesis

Base `b3a04fe`. Three commits on `main`, all GPG-signed:

| SHA | Subject |
|---|---|
| `11b93e1` | `fix(desktop): ship server package data in the bundle` |
| `7bc7eb8` | `feat(desktop): consolidate bundle onto one OpenMP copy` |
| `cfedf6b` | `feat(desktop): gate the bundle on real model output` |

## 1. AC1 / AC2 Part A — the captured RED state, before the fix

Measured against the m7 bundle at `var/desktop-package/dist/arxmcp-desktop-child/`,
built from `b3a04fe`, before any edit:

```
$ find . -name 'libomp*.dylib' | xargs ls -la
-rwxr-xr-x  750624  ./_internal/faiss/.dylibs/libomp.dylib
lrwxr-xr-x      22  ./_internal/libomp.dylib -> torch/lib/libomp.dylib
-rwxr-xr-x  856096  ./_internal/torch/lib/libomp.dylib

$ find . -name 'libomp*.dylib' -type f -exec shasum -a 256 {} \;
7989202b0c9fffedcaa4f7dfb1beb7bc377e4394b3a9cd2c32ada3d66ef22170  ./_internal/faiss/.dylibs/libomp.dylib
cc166d3963321a433c8227766424cd24639acd266230cecc8d62e54e8c118c30  ./_internal/torch/lib/libomp.dylib
```

**Two regular files** — the guard `_require_single_libomp` raises
`bundle must carry exactly one OpenMP runtime file, found 2` against this
tree. GREEN after the exclusion; `report.json` from the post-fix build:

```json
"libomp": {
  "regular": [{"path": "_internal/torch/lib/libomp.dylib",
               "sha256": "cc166d39...", "size": 856096}],
  "symlinks": {"_internal/libomp.dylib": "torch/lib/libomp.dylib"}
}
```

Mechanism: a post-`Analysis()` filter on `analysis.binaries` drops the
`faiss/.dylibs/libomp.dylib` TOC entry before `COLLECT()`, per the brief's
Option A. No Mach-O load command and no ad-hoc signature is touched — the
entry is simply never copied and never signed, which is what keeps this
composable with the deferred Developer ID work. The build fails closed when
the exclusion matches nothing, when it would leave no OpenMP runtime, and
when the shipped tree ends up with any count but one.

## 2. AC2 Part B — the mechanism REPRODUCED, and the reason the brief's design was incomplete

**Result: a genuine crash, on the frozen artifact class.** `subprocess.run`
reports `returncode == -6` (SIGABRT); a shell-observed launch of the same
binary reports `134`. Both are asserted; the test reads
`proc.returncode`, never a pipeline's.

The brief's §4b proposal — re-add the orphan and rewrite
`_swigfaiss.abi3.so`'s `LC_LOAD_DYLIB` to `@loader_path/.dylibs/libomp.dylib`
— was tried FIRST and **did not reproduce**:

| # | Arm | Result |
|---|---|---|
| 1 | Frozen bundle, natural resolution | exit 0, `openmp_images == [_internal/torch/lib/libomp.dylib]` |
| 2 | Orphan re-added + consumer load command rewritten to `@loader_path/.dylibs/…` | **exit 0**, one image — faiss's copy this time |
| 3 | Arm 2 **plus** the orphan's install name restored to `/DLC/faiss/.dylibs/libomp.dylib` | **exit 134 / rc -6**, `OMP: Error #15` |
| 4 | Arm 3's exact recipe, but sourcing the orphan straight from the build venv's `faiss/.dylibs/libomp.dylib` (which already carries the upstream install name) against a post-fix bundle | **exit 134 / rc -6**, `OMP: Error #15` |

Arm 2 is the load-bearing negative. dyld dedupes by **install name**, and
PyInstaller rewrites *both* copies' IDs to the same `@rpath/libomp.dylib`.
So while the orphan carries a PyInstaller-normalised ID, pointing the
consumer at it merely swaps which single image gets mapped — it never maps
two. Only restoring the upstream ID (`/DLC/faiss/.dylibs/libomp.dylib`,
distinct from torch's `/opt/llvm-openmp/lib/libomp.dylib`) makes the second
image real.

That is the finding: **the m7 bundle was safe by accident of ID
normalisation, not of rpath ordering alone.** The shipped test uses arm 4 —
upstream wheel bytes, no `install_name_tool -id` needed — so it restores the
literal pre-PyInstaller state rather than a synthesised one. Injection runs
on a hardlink clone with the mutated file's link broken first, and the test
re-reads the shipped `_swigfaiss.abi3.so` afterwards to prove
`@rpath/libomp.dylib` is still its load command.

The AFTER arm is permanent: `arxmcp-desktop-probe --mode omp` runs a real
FAISS `IndexFlatL2` add+search then real 4-thread Torch matmul in ONE frozen
process, exits 0, and reports the OpenMP images **dyld actually mapped**
(`_dyld_get_image_name`) — a directory listing cannot distinguish "present"
from "loaded".

## 3. AC3 — `KMP_DUPLICATE_LIB_OK`

Re-asserted on both new compute paths, by the process that does the compute:
`probe_entry.FORBIDDEN_ENV` and `tools/desktop_model_probe.FORBIDDEN_ENV`
each raise on `KMP_DUPLICATE_LIB_OK` / `PYTHONHOME` / `PYTHONPATH` and on
`DYLD_*` / `LD_*` before any import. Both are launched with an explicit
environment, never the runner's — `tests/conftest.py` sets the variable
session-wide, so an inherited env would make the assertion vacuous. A fast
test drives the rejection path directly.

## 4. AC4 / AC5 — the real-model gate

**Observed run-to-run variation: exactly 0.0.** Four consecutive probe runs
on this host — `OMP_NUM_THREADS` 2, 3 and 4, and both offline
(`HF_HUB_OFFLINE=1`) and online hub resolution — produced bit-identical
float32 output: max |Δ| over all 3×1024 vector elements = `0.0`, max |Δ|
over the 3 rerank scores = `0.0`.

**Tolerance: `1e-6`, both surfaces.** Justified as pure headroom over a
measured-zero drift — roughly 4e-6 of the largest observed element (0.252) —
for float32 CPU reduction-order differences on a different arm64 host. It is
250× TIGHTER than the `1e-4` placeholder `tests/test_query_encoder.py`
carried but never shipped, and it is not a number sized to make a drifting
assertion pass. Loosening it requires a fresh measurement recorded here.

The fixture is greenfield (`tests/fixtures/desktop_model/golden_v1.json`,
87 KB): three queries reused from existing suites plus three
`(query, body)` rerank pairs. It is discriminating rather than merely
present — the on-topic body scores `0.987` against `1.63e-05` and `1.62e-05`
for the two off-topic ones, so a mis-loaded model cannot coincidentally
match. Fast tests pin the fixture's revisions to the live
`BGE_M3_COMMIT_SHA` / `BGE_RERANKER_COMMIT_SHA` constants, so a pin bump with
a stale golden fails as a pin problem instead of reading as corruption.

Encoding runs through the PRODUCTION chains
(`server.query_encoder._encode_query_sync`,
`server.resources._load_reranker_or_raise` + `rerank._rerank_sync`) — never a
re-implementation.

AC5: the bundle walk finds zero `.safetensors/.ckpt/.pt/.pth/.gguf/.onnx/.h5`
files, zero `pytorch_model*`, and no `models--*` / `blobs` tree, with a
≥4000-file floor so a broken walk cannot read as clean. `HF_HOME` resolves to
`~/.cache/huggingface/hub`, outside the bundle, and both pinned snapshots are
asserted present there.

**The frozen child boots.** `arxmcp-desktop-child` handshakes, and reports
`warm == {"embedder": true, "lancedb": true, "reranker": true}` on
`/readyz` 200 with a KMP-free environment and the external cache.

## 5. Unplanned finding — the bundle could not boot at all

Wiring that boot surfaced a defect m7's gate structurally could not see: **no
`server` package-data file was collected into the bundle.** PyInstaller ships
only `.py`, so `router_patterns.yaml`, `server/schemas/*.json` and the
operator console's `server/frontend/{templates,static}` were all absent, and
`create_app()` raised `RuntimeError: Directory '.../server/frontend/static'
does not exist` before the child could bind. m7's only launch was a *rejected*
one (`rc == 2`), which fails before app construction — so its green gate and
a non-bootable artifact were consistent.

Fixed with `hook-server.py` (`collect_data_files("server")`) and guarded by a
DERIVED gate test comparing the bundle against the build venv's installed
tree, so a future data file cannot drop out silently. This is CLAUDE.md
§4.5b's rule one layer down: declaring a package ships its modules and
nothing else, at BOTH the wheel and the freeze boundary.

**Deferred, not fixed:** `ingest/*.sh`, `tools/*.sh`, `tools/seed-papers.txt`
and the whole `ops/` tree are likewise uncollected. None is on the child's
runtime path, so they are out of m8's scope — but an operator-facing desktop
build that expects `ops/` will need the same hook treatment.

## 6. Gate results

| Gate | Result | Time | Baseline |
|---|---|---|---|
| `cargo fmt --all -- --check` | PASS | 1 s | — |
| `cargo clippy … -D warnings` | PASS (0 warnings) | 4 s | — |
| `make desktop-package-check` | **26 passed** | **255 s** | 18 passed / 159 s |
| `make desktop-conformance` | exit 0, **42 + 30 + 33** | 62 s | 42 + 30 + 33 |
| `make test` | **5142 passed, 76 skipped, 1 xfailed** | **337 s** | 5135 / 68 / 1 |
| `make desktop-model-check` (new) | **7 passed** | **177 s** total (135 s build + 42 s tests) | n/a |

`make test` deltas reconcile exactly: **+7 passed** are the new fast tests
(4 in `test_desktop_package.py`, 3 in `test_desktop_bundled_model.py`);
**+8 skipped** are the new opt-in gate tests (4 + 4), correctly deselected by
`_OPT_IN_MARKERS`. No test lost, no runtime regression (337 s vs ~358 s).

`desktop-package-check` grew 159 s → 255 s. The cost is the probe EXE's
Analysis: giving it `hiddenimports=["faiss"]` (faiss's Python half lives in
the PYZ; only the SWIG extension lands on disk) pulls numpy's module graph
into a second Analysis, and `desktop-package-check` pays it twice for its two
independent builds. torch and transformers cost nothing extra — they are
collected as on-disk source under `_internal` and resolve through the normal
path finder at runtime.

`desktop-model-check` is deliberately a SEPARATE target: ~4.6 GB of real
weights and a frozen boot do not belong in `make test`, and its 42 s of test
time is on top of a 135 s bundle build it depends on.

## 7. Deviations from the brief

- **§4b's BEFORE arm needed a third mutation the brief did not name** — the
  orphan's install name. See §2; the brief explicitly flagged this design as
  unproven and asked for empirical validation, which is what §2 records.
- **AC4 runs the golden encode against the source-tree production chain, not
  through a frozen EXE.** The brief (§5) rates the two equally honest — the
  encode code is byte-identical — and a `model` mode on the probe would have
  pulled the whole `server`/`ingest` graph into a second PYZ, roughly doubling
  `desktop-package-check` again. The frozen half of AC4 is covered by the real
  frozen-child boot with the external cache, and AC5's weight scan is a
  filesystem assertion on the frozen tree.
- **`hook-server.py` was not in scope** and is committed separately; without
  it AC4's boot half is unreachable.
- **No `install_name_tool` in the shipping path**, per the brief — it appears
  only inside the fault-injection test, on a disposable clone.

## 8. External writes

None performed. `git push origin main` is required to publish these three
commits and is left to the session owner.
