# Research — decomposing desktop-distribution-e4's three actionable Spike-1 blockers

**Scope:** Spike-1 release blockers 1 (OpenMP collision), 2 (real BGE-M3), 5
(packaging hygiene). Blockers 3 (macOS-14 floor) and 4 (Developer ID
signing/notarization) are out of scope — externally gated, covered by other
agents. Source: `.claude/notes/spikes/desktop-distribution-spike-1.md`
"Release blockers" §.

---

## Blocker 1 — OpenMP FAISS/Torch collision

### Reproduction — established, with the correct method

The task's own probe ("imported `lancedb, faiss` then `torch` with no
abort") does NOT reproduce, and I confirmed why: a bare `import` never
triggers OpenMP's runtime-init collision — `libomp.dylib` is `dlopen`'d
lazily, only when a parallel region actually runs (a real FAISS search or a
multi-threaded Torch op). I reproduced it correctly in `.venv` (the same
`faiss-cpu`/`torch` wheels `make wheel-check-full` would install — see
below for why this venv is a valid proxy) with:

```
env -u KMP_DUPLICATE_LIB_OK -u OMP_NUM_THREADS .venv/bin/python -c "
import numpy as np, lancedb, faiss
idx = faiss.IndexFlatL2(4)
idx.add(np.random.rand(100,4).astype('float32'))
idx.search(np.random.rand(5,4).astype('float32'), 3)   # actually USE faiss
import torch
x = torch.randn(64, 512); w = torch.randn(512, 512)
for _ in range(20): x = torch.relu(x @ w)               # actually USE torch
"
```

Result: `OMP: Error #15: Initializing libomp.dylib, but found libomp.dylib
already initialized.` — process exits **134 (SIGABRT)**.

**Why this venv is a valid stand-in for the installed wheel, without
running the full ~4–15 min `wheel-check-full` build.** `faiss-cpu` and
`torch` are always installed as regular (non-editable) wheels into
site-packages — their bundled `.dylibs`/`lib` layout and `LC_RPATH`/
`LC_LOAD_DYLIB` entries are byte-identical whether `arxmcp` itself is
editable-installed (this venv) or wheel-installed (`wheel-check-full`'s
throwaway venv). The collision lives entirely inside the third-party
dependency wheels, not in how `arxmcp` is packaged. `pyproject.toml:129,182,254`
pins `torch>=2.0,<3` (installed: 2.11.0), `lancedb>=0.30.2,<0.35` (installed:
0.30.2), `faiss-cpu>=1.7` (installed: 1.13.2) — the same versions
`wheel-check-full` resolves. The implementer should still run
`make wheel-check-full` once during m7 to confirm end-to-end, but this
finding already proves the collision is real and gives an executable
regression fixture today.

**Why no existing gate catches it.** `tools/wheel_install_check.py`'s
`full` mode (`tools/wheel_install_check.py:41-58`) only boots
`ARXMCP_BOOTSTRAP_MODE=1` and polls `/healthz` — it never creates a
notebook or runs retrieval, so it never actually exercises FAISS search +
Torch inference in the same process. `make test` never crashes on this
because `tests/conftest.py:37-39` sets `KMP_DUPLICATE_LIB_OK=TRUE` at
module load (test-only; cleared at session end per `tests/conftest.py:67-77`,
F10 fix from the E08_S03 critique) — see `CLAUDE.md:837-842` gotcha 1,
which explicitly states "Production Linux containers don't need it." This
means the collision is **macOS-desktop-packaging-specific**: it has never
been hit in CI/Docker/prod because those run Linux, and it has never been
hit in local dev because `conftest.py` papers over it. `KMP_DUPLICATE_LIB_OK`
is forbidden for the desktop bundle by the spike (and would be a silent
`s/crash/possibly-wrong-results/` swap, not a fix).

### Native library inventory (source venv, representative of the dependency closure)

| File | SHA-256 | Loaded via |
|---|---|---|
| `.venv/lib/python3.12/site-packages/faiss/.dylibs/libomp.dylib` | `5c8996f...` | `faiss/_swigfaiss.abi3.so` `LC_LOAD_DYLIB @loader_path/.dylibs/libomp.dylib` (fully-qualified relative path, not `@rpath`) |
| `.venv/lib/python3.12/site-packages/torch/lib/libomp.dylib` | `a454b03...` | `torch/lib/libtorch_cpu.dylib` `LC_LOAD_DYLIB @rpath/libomp.dylib` + `LC_RPATH @loader_path` |

Confirmed via `find .venv -iname "*.dylib" | xargs basename | sort | uniq -c`
that `libomp.dylib` is the **only** duplicated native library name across
the entire dependency closure (no other collision to hunt for).

Per the ADR (`.claude/notes/spikes/desktop-distribution-spike-1.md:38-40`),
in the **frozen PyInstaller bundle** `_swigfaiss.abi3.so`'s `LC_RPATH`
becomes `@loader_path/..` and resolves `_internal/libomp.dylib`
(`cc166d…`) instead of its own nested copy (`798920…`) — i.e. PyInstaller's
onedir collection step already accidentally consolidates the two dylibs
into one shared copy at the bundle root, and happens to pick the
FAISS-flavored one. That is why m2's frozen probe passed without any
workaround. This is currently **accidental, not designed** — nothing
verifies which copy wins, and a future PyInstaller/hooks-contrib version
bump, or a new native dependency that also ships `libomp.dylib`, could
silently flip which copy is kept or reintroduce two copies (e.g. if
hooks-contrib's `faiss` hook changes to preserve `faiss/.dylibs/` as a
distinct nested dir instead of flattening it — PyInstaller's default
`onedir` behavior for `.dylibs`-suffixed collection dirs is version-
sensitive).

### Fix direction

1. Consolidate to one canonical `libomp.dylib` intentionally, not by
   accident of collection order. Two options, in order of preference:
   - **A — PyInstaller-side pin:** add a `hook-faiss.py` (or extend
     hooks-contrib's) that explicitly excludes `faiss/.dylibs/libomp.dylib`
     from collection and rewrites `_swigfaiss.abi3.so`'s `LC_LOAD_DYLIB`
     to reference the retained copy (e.g. via `install_name_tool` in a
     post-collection build step), so exactly one `libomp.dylib` exists in
     the bundle by construction, and the choice survives a
     PyInstaller/hooks-contrib upgrade.
   - **B — dependency-side:** investigate whether a newer `faiss-cpu`
     wheel drops its bundled `libomp.dylib` and links `@rpath` instead
     (some faiss-cpu macOS wheels moved to Homebrew's `libomp` via
     `@rpath`); this is a version-bump exploration, not guaranteed to
     exist, and would still need the consolidation regression test below
     regardless.
2. **Regression test that actually discriminates.** A test that only
   imports both libraries proves nothing (I just demonstrated that). The
   test must, against the FROZEN bundle:
   - Run the exact repro sequence above (FAISS `add` + `search`, then a
     real multi-threaded Torch op) inside the frozen `onedir` tree via a
     subprocess launched with the sanitized environment
     (`tools/desktop_sidecar_spike.py:launch_environment`, which already
     forbids `KMP_DUPLICATE_LIB_OK` at `tools/desktop_sidecar_spike.py:14-15,42-49`)
     and assert exit code 0 (not 134).
   - Separately assert exactly ONE regular file named `libomp.dylib` (or
     any OpenMP-runtime dylib by content-hash family) exists anywhere in
     the bundle's `_internal/` tree — a filesystem-level guard that fails
     loudly if a future dependency bump reintroduces a second copy, even
     before the process-level probe would catch it.
   - Both checks belong together: the file-count check catches drift
     early and cheaply; the process-level check is the ground truth that
     the consolidation is load-bearing, not cosmetic.

### What must be true to call it closed
- A committed, intentional consolidation mechanism (hook, spec-time
  post-processing, or dependency pin) — not an accident of PyInstaller's
  default collection order.
- A regression test with BOTH the single-file assertion and the real
  FAISS-search-then-Torch-inference process-level assertion, run against
  the actual frozen bundle (not a fixture), exit code checked.
- `KMP_DUPLICATE_LIB_OK` absent from the production launch environment
  (already enforced defensively by `tools/desktop_sidecar_spike.py`'s
  `FORBIDDEN_ENV`, but that guard alone does not prove no collision
  exists — it only proves the workaround wasn't used).

### Verification commands
- Fast dependency-level repro (no build needed, ~2s): the `env -u ... .venv/bin/python -c "..."` snippet above; must exit 134 BEFORE the fix is designed as a baseline, and exit 0 with the real FAISS+Torch compute path once the desktop entry point / launch environment applies the fix (this alone does not close the blocker — it is dependency-level, not bundle-level).
- Bundle-level: build the `onedir` artifact (`tools/desktop_sidecar_spike.py` mode=`probe`, extended to run the real compute path, or a new `arxmcp-desktop-omp-check.py`), launch via `launch_environment`, assert exit 0.
- `make wheel-check-full` extended to run one real notebook ingest + query cycle so the collision is caught even in the non-frozen installed-wheel gate (cheap incremental win independent of the PyInstaller fix; currently `wheel-check-full` boots bootstrap mode only, per `tools/wheel_install_check.py:41-58`).

### LOC / effort estimate
- Fix mechanism (hook or post-processing step): 60–150 LOC + a `.spec`
  hook file.
- Regression tests (file-count + process-level): 100–180 LOC, mirrors
  `tests/test_desktop_sidecar_spike.py`'s style (90 LOC precedent).
- Total: **~200–350 LOC**, M complexity. Honest risk: if option A (explicit
  `install_name_tool` rewrite) proves fragile across PyInstaller versions,
  this could grow toward the L band — flag at implementation time, don't
  pre-commit to a size.

### Dependencies
- Needs the `.spec` file that Blocker 5 must create (no `.spec` exists
  today — see Blocker 5). These two blockers should land in the SAME
  milestone or with Blocker-5's spec landing strictly first.

---

## Blocker 2 — Real externally-seeded BGE-M3

### Cache status — already present, no download needed

```
~/.cache/huggingface  → 20 GB total
models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181/   (pinned SHA — matches ingest/embedder.py:132)
models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e/  (pinned SHA — matches server/retrieval/rerank.py:117)
```

Both pinned revisions are the `refs/main` pointer in this cache
(`refs/main` for `bge-m3` = `5617a9f6...`, exact match). BGE-M3's pinned
snapshot ships `pytorch_model.bin` (2.1 GiB blob
`b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38`) —
**not** `model.safetensors`; a second, unpinned/newer snapshot
(`9a0624b8...`, `refs/main` moved past it) DOES have `model.safetensors`
(2.1 GiB, `993b2248...`), confirming the spike's claim that the *pinned*
commit predates BGE-M3's safetensors upload. The reranker's pinned
snapshot is `.bin`-only too (2.1 GiB blob `d9e3e081...`).

**This means Blocker 2's milestone needs zero network access on this
host** — the exact pinned weights are already on disk. A CI/fresh-machine
run would still need the ~4.2 GiB download; the milestone's acceptance
criteria and estimate should account for both paths (cached vs. cold).

### Existing safetensors-policy machinery — and the embedder's documented gap

`server/model_loader.py` is the shared Threat-6 guard module:
- `validate_model_revision()` (`server/model_loader.py:59-90`) — refuses
  any non-40-char-hex `revision=`.
- `assert_no_bin_in_snapshot()` (`server/model_loader.py:135-190`) — walks
  the HF cache snapshot dir and raises `ModelPinningError` if any `.bin`
  weight file is present (excluding `training_args.bin`).

**The reranker enforces both** — `server/resources.py:2131` passes
`use_safetensors=True` and `server/resources.py:2147` calls
`assert_no_bin_in_snapshot(RERANKER_MODEL_ID, BGE_RERANKER_COMMIT_SHA)`
right after load.

**The embedder does NOT** — `ingest/embedder.py:339-353` has an explicit,
already-written comment explaining why: the pinned BGE-M3 SHA ships only
`pytorch_model.bin`, so `use_safetensors=True` would break the load, and
bumping the SHA would invalidate every cached embedding under
`var/arxmcp/corpus/embeddings/` (an E04_S02 MVCC re-encode, out of scope
for the security milestone that wrote this comment). This IS the
documented "safetensors-policy exception" the milestone brief references
— it is not new information, it's a known, named, load-bearing gap
tracked in `.claude/docs/security-threat-6-audit.md` and
`.claude/notes/milestones/E13_S10/` (a filed issue referencing exactly
this gap: `_file_issues.py:107-117`).

**Implication for m-whatever:** this milestone is NOT "add the missing
safetensors enforcement to the embedder" (that's E13_S10's pre-existing,
separately tracked, and would force a corpus-wide re-embed — explicitly
out of scope per that issue). It is "prove BGE-M3 loads and runs
correctly OUTSIDE the app bundle, from an external HF cache, in the
desktop runtime" — the `.bin` weight format itself is an accepted,
already-decided exception; Blocker 2 is about desktop bundling policy
(no model in the bundle) and exercise honesty, not about closing the
safetensors gap.

### Opt-in gates already in place, reusable as-is

- `pyproject.toml:366` — `requires_model` marker: "tests that download /
  load a real ML model... Skipped by default in CI; opt-in via `pytest -m
  requires_model` AND the per-model env-var".
- `ARXMCP_RUN_REAL_BGE_M3=1` — gates `tests/test_query_encoder.py:803-805`
  (golden-file drop test).
- `ARXMCP_RUN_REAL_BGE_RERANKER=1` — gates
  `tests/retrieval/test_rerank.py:743-746` (`TestOnPathRequiresModel`).
- `tests/test_embedder.py:22` documents the same pattern for the embedder
  proper.
- `tests/conftest.py:94-150` implements the "opt-in marker deselection"
  contract (issue #206): `requires_model`-marked tests are ACTUALLY
  skipped by default (not just documented as skippable) and a collection-
  time guard prevents marker-name drift from silently no-opping the skip
  — same "ALL-OR-NOTHING with zero skips" pattern
  `desktop-conformance`/`requires_desktop_stack` already uses
  (`tests/conftest.py:43-56` / `Makefile:154-161`).

**Reuse pattern for the bundled-runtime gate:** mirror
`requires_desktop_stack` exactly — a new marker (e.g.
`requires_bundled_model`) gated by an env var the Makefile sets only when
running the real-model desktop check, following the SAME "both names
required, collection-time zero-skip enforcement" pattern already proven
in `tests/conftest.py:43-88`. Do not invent a third gating mechanism.

### What "exercised" must honestly mean

Per the task's own framing — loading weights is not the same as producing
correct output. The gate must assert on OUTPUT, not just successful
`from_pretrained`:

1. **Load-only is insufficient.** `AutoModel.from_pretrained(...)` can
   succeed even with corrupted or truncated weights if the tensor shapes
   happen to match, or silently substitute an incompatible checkpoint on
   `strict=False`.
2. **Minimum honest bar:** encode a fixed small set of known input
   strings through the REAL bundled/external-cache model and compare
   against a golden fixture with `numpy.allclose` at a tight tolerance —
   `tests/test_query_encoder.py:784` already does exactly this pattern
   ("weekly with `ARXMCP_RUN_REAL_BGE_M3=1` can drop the golden file" —
   i.e. there is already a golden-vector regression precedent to extend,
   not invent from scratch).
3. **For the desktop bundle specifically**, additionally assert:
   - the model load path resolves to the EXTERNAL HF cache (or an
     explicit external model directory), never anything under the
     read-only application bundle tree — reuse
     `tools/desktop_sidecar_spike.py:validate_frozen_paths` semantics but
     inverted (assert the model directory is OUTSIDE the bundle, mirroring
     the existing "everything mutable is outside the bundle" contract from
     m2).
   - the reranker path, since `ARXMCP_ENABLE_RERANK=1` is already a known
     desktop-child env var per `pyproject.toml:374`'s
     `requires_desktop_stack` docstring — the m6 fault-matrix precedent
     already loads a third model this way for its own reasons; this
     milestone's real-model check should reuse that same launch
     configuration rather than inventing a second one.

### What must be true to call it closed
- A gate (opt-in, mirroring `requires_desktop_stack`) that boots the
  desktop child / bundle with `ARXMCP_ENABLE_RERANK=1`, resolves BGE-M3
  and the reranker from an EXTERNAL cache dir (never inside the bundle),
  encodes a fixed golden input set, and asserts vector-level correctness
  (not just successful load) against a committed golden fixture.
- Explicit assertion that no model file exists anywhere under the
  application bundle's read-only tree (extends the m2/spike-1 "everything
  mutable stays under the data root" proof to "everything model-shaped
  stays outside the bundle regardless of mutability").
- Documented, tested behavior for the cold-cache path (first-run
  download) — even if only smoke-level, since a clean-machine operator
  won't have this host's warm cache. Must not silently fall back to
  loading nothing or to a wrong revision.

### Verification commands
- `ARXMCP_RUN_REAL_BGE_M3=1 pytest -m requires_model tests/test_query_encoder.py` (existing, reusable as-is for the non-desktop half).
- `ARXMCP_RUN_REAL_BGE_RERANKER=1 pytest -m requires_model tests/retrieval/test_rerank.py::TestOnPathRequiresModel` (existing).
- New: `DESKTOP_SUPERVISOR_BIN=... ARXMCP_FIXTURE_SIDECAR=... pytest -m requires_desktop_stack tests/test_desktop_bundled_model.py` (new file) — boots the REAL desktop child (not the fixture sidecar) with external cache pointed at `~/.cache/huggingface`, encodes golden inputs, asserts vectors.

### LOC / effort estimate
- New test file + golden fixture: 150–250 LOC (mirrors
  `tests/test_query_encoder.py`'s existing real-model test shape).
- External-cache path wiring for the desktop child (if not already fully
  parameterized — needs verification against `server/desktop_child.py`,
  which m5 built; likely small since `ARXMCP_ENABLE_RERANK`/model env vars
  are believed already threaded through per the `requires_desktop_stack`
  docstring): 30–80 LOC.
- Total: **~200–350 LOC**, M complexity, LOW risk given the model is
  already cached and the marker/golden-fixture patterns already exist —
  this is mostly wiring and assertion-writing, not discovery.

### Dependencies
- Needs `apps/desktop`'s m5/m6 real-child boot path (`DESKTOP_SUPERVISOR_BIN`,
  `server.desktop_child`) — already shipped. Needs the `.spec`/bundle from
  Blocker 5 ONLY if the AC requires testing inside the actual frozen
  `onedir` artifact rather than the unfrozen desktop-child process; the
  cheaper, still-honest first cut can run against the unfrozen desktop
  child (already real) and defer the frozen-bundle variant.

---

## Blocker 5 — Packaging hygiene

### `.spec` file — does NOT exist, must be created from scratch

Confirmed via `find . -iname "*.spec"` (git-tracked tree only) — zero
hits. `.claude/notes/milestones/desktop-distribution-spike-1/implement/synthesis.md:5`
confirms the spike's spec "stayed in `/private/tmp/arxmcp-sidecar-
spike1.hAKhhD`" (per the ADR, `.claude/notes/spikes/desktop-distribution-
spike-1.md:17`) — nothing was committed, and that temp dir is gone
(verified: not present on this host). `pyproject.toml` has **no**
`pyinstaller` or `pyinstaller-hooks-contrib` dependency declared anywhere.
This blocker's `.spec` work is 100% new, not "restore something that
existed."

`tools/desktop_sidecar_spike.py` (192 LOC, committed) IS reusable as the
frozen entry-point script the `.spec`'s `Analysis(scripts=[...])` should
point at — it already implements `multiprocessing.freeze_support()`
(`tools/desktop_sidecar_spike.py:176`, inside `main()`, called first) and
the sanitized/offline launch-environment + frozen-path-confinement guards
this blocker needs to "retain." Confirm at implementation time whether
`server/desktop_child.py` (the REAL production entry point per m5, not
this spike script) also calls `freeze_support()` — if not, that's this
milestone's actual "productize" work item, since the spike script was
explicitly "disposable" (docstring line 1) and the desktop-child boot path
built in m5 is what m7 ships.

### `latex2mathml` data hook — the missing file, confirmed by name

`unimathsymbols.txt` lives at `latex2mathml/unimathsymbols.txt` inside the
installed package (verified path in `.venv/lib/python3.12/site-packages/
latex2mathml/unimathsymbols.txt` — a non-`.py` data file PyInstaller's
default module-scanning does NOT collect automatically). The spike's ADR
(`.claude/notes/spikes/desktop-distribution-spike-1.md:23-24`) records
this exact gap as the ONE bounded spec correction needed after first
launch exposed it: "added `latex2mathml/unimathsymbols.txt` after the
first server launch exposed its absence." `server/handlers/equation.py:37`
imports `latex2mathml.converter.convert` directly — this is a live server
code path (query-time LaTeX→MathML conversion per
`server/handlers/equation.py:10`), not a dev-only utility, so the hook
must ship in every build, not be rediscovered by trial each time. A
`hook-latex2mathml.py` using `PyInstaller.utils.hooks.collect_data_files`
is the standard fix shape (~10 LOC) — no `pyinstaller-hooks-contrib`
upstream hook exists for this package (it's a narrow academic-math
library, not covered by the contrib project), so it must be a
project-owned hook, either under a new `packaging/pyinstaller-hooks/`
dir or inline in the `.spec`'s `Analysis(datas=[...])`.

### `direct_url.json` — reproduced the leak directly

Built the real wheel (`uv build --wheel`) and installed it into a
throwaway venv exactly as `pip install <path-to-wheel>` would:

```
$ cat arxmcp-0.1.0.dist-info/direct_url.json
{"archive_info": {...}, "url": "file:///tmp/arxmcp-wheel-check/arxmcp-0.1.0-py3-none-any.whl"}
```

Confirmed this is the ONLY file in the entire installed tree containing an
absolute build-root path — `grep -rl "/tmp/arxmcp-wheel-check"` across the
whole installed site-packages tree returns exactly `direct_url.json`. No
stray `.pyc` files were produced (pip does not compile bytecode by
default). **This means the wheel-install layer itself is otherwise clean**
— the fix is narrowly "strip or rewrite `direct_url.json` post-install,
pre-freeze" (a small, mechanical step), NOT a broad packaging audit. The
"scan every regular file" AC should still be a real recursive scan over
the FROZEN bundle (not just the wheel), because PyInstaller's own
Analysis/collection step is a second place a build-root string could leak
(e.g. compiled `.pyc` `co_filename` attributes, which PyInstaller DOES
embed from the build machine's absolute source paths unless stripped) —
this is a discovery item for the milestone, not yet measured on this host.

### What must be true to call it closed
- A committed `.spec` (or equivalent PyInstaller Python build script) that
  builds deterministically from `tools/desktop_sidecar_spike.py`'s pattern
  (or `server/desktop_child.py` — decide which is the real entry point at
  implementation time) with `multiprocessing.freeze_support()` verified as
  the first call in `main()`.
- A `latex2mathml` data hook shipping `unimathsymbols.txt`, exercised by a
  regression test that imports `server.handlers.equation` inside the
  frozen bundle and calls a real conversion (not just checks the file
  exists on disk — the m2 lesson "a test that merely imports successfully
  does not discriminate" applies here too: assert the CONVERTED MathML
  output is correct, not just that import didn't crash).
- `direct_url.json` stripped or rewritten to remove the build-root URL
  post-install, pre-freeze (or post-freeze, scanning the bundle) — as part
  of the same recursive build-root-string scan.
- A recursive regular-file scanner run against the FROZEN bundle (not the
  wheel) asserting zero occurrences of the build machine's temp-root
  prefix (e.g. `/private/tmp`, the operator's `$HOME`, `/Users/<username>`)
  in any regular file's bytes.
- The unrelated-CWD, read-only, native-closure, and model-external gates
  from spike-1 (already measured once, ad-hoc) become PERMANENT,
  re-runnable regression tests — not re-litigated each spike, wired into
  `make desktop-conformance` or a new `make desktop-package-check` target.

### Verification commands
- `uv build --wheel --out-dir /tmp/<x> && <venv>/bin/pip install --no-deps /tmp/<x>/*.whl && cat .../direct_url.json` — confirms the leak exists pre-fix / is absent post-fix.
- New: `python tools/desktop_package_scan.py --bundle <onedir-path>` (new script) — recursive byte-grep for build-root strings, exits non-zero on any hit.
- `make desktop-conformance` extended to run the above scan, plus a real (not smoke) `latex2mathml` conversion through the frozen bundle's Python.

### LOC / effort estimate
- `.spec` file + `hook-latex2mathml.py`: 80–150 LOC (spec files are dense
  but short; the hook is ~10-15 LOC).
- `direct_url.json` sanitization step (build-script or post-install hook):
  20–40 LOC.
- Recursive build-root-string scanner + regression test: 100–180 LOC.
- `freeze_support()` audit/fix on the real `server/desktop_child.py` entry
  point (unknown until read — flag as a discovery item, budget 0-50 LOC).
- Total: **~250–420 LOC**, M complexity. This is the widest-uncertainty
  blocker because "no `.spec` exists" means the milestone is greenfield
  PyInstaller-build authoring, not incremental fixing — treat the low end
  of the range with skepticism.

### Dependencies
- Should land FIRST — Blockers 1 and 2's bundle-level regression tests
  both need a real, buildable `.spec` to run against. Blocker 1's "single
  `libomp.dylib` in the bundle" filesystem check and Blocker 2's "model
  outside the bundle, bundle content otherwise closed" check are both
  meaningless without a committed, repeatable build.

---

## Proposed milestone decomposition

Two milestones, sequenced. Blocker 5 (the `.spec` + packaging hygiene) is
the enabler every other blocker's regression test needs to run against a
real, repeatable bundle — it must land first. Blockers 1 and 2 are
independent of each other (different subsystems: native-library
consolidation vs. model-loading policy) and can be combined into one
milestone without violating single-responsibility, because both are
"prove a spike-1 finding with a permanent regression gate against the now-
buildable bundle" — the same shape of work, reusing the same bundle
infrastructure m7 produces. Splitting them into two milestones was
considered and rejected below (Alternatives).

### desktop-distribution-m7 — Reproducible PyInstaller bundle and packaging hygiene

**Description.** Commit a PyInstaller `.spec` (or equivalent build
script) building from the real desktop-child entry point
(`server/desktop_child.py`, confirming/adding `multiprocessing.
freeze_support()` as its first call — spike-1's `tools/
desktop_sidecar_spike.py:176` is the disposable precedent, not the
shipped path), including a project-owned `hook-latex2mathml.py` that
collects `unimathsymbols.txt`. Add a post-build sanitization step that
strips or rewrites `arxmcp-0.1.0.dist-info/direct_url.json` before
freezing, and a recursive scanner that fails the build if any regular
file in the frozen bundle contains the build machine's absolute
temp/home path. Wire the whole thing into a new `make desktop-package`
target that produces the artifact `make desktop-conformance` and future
signing milestones (e4's Developer ID work) will consume.

**Acceptance criteria.**
- [ ] `make desktop-package` builds a deterministic `onedir` bundle from a
      committed `.spec`; two consecutive builds from the same commit
      produce byte-identical `tree_manifest` output (extends
      `tools/desktop_sidecar_spike.py:tree_manifest`'s existing hash
      scheme) excluding only files the build tool itself declares
      non-deterministic (documented, not silently ignored).
- [ ] The frozen bundle's Python imports `server.handlers.equation` and
      converts a fixed LaTeX fixture to MathML with byte-identical output
      to the source-tree conversion — proving the `latex2mathml` data hook
      ships the real symbol table, not just that import didn't crash.
- [ ] `multiprocessing.freeze_support()` is the first statement inside the
      production entry point's `main()`/`if __name__ == "__main__":`
      guard, verified by a test that launches the frozen executable and
      confirms no duplicate top-level process spawn occurs (the classic
      Windows/frozen-multiprocessing failure mode; verify on macOS too
      since `spawn` is the default start method there).
- [ ] `arxmcp-0.1.0.dist-info/direct_url.json` inside the frozen bundle
      contains no `file://` URL pointing at a build-machine path — either
      absent, or rewritten to a synthetic/generic value.
- [ ] A recursive regular-file scan of the entire frozen bundle asserts
      zero occurrences of the build host's temp-root prefix, `$HOME`
      prefix, or the invoking username, across ALL regular files
      (including compiled `.pyc`, if PyInstaller's Analysis step embeds
      `co_filename` from the build machine — assert this explicitly, do
      not assume it's absent).
- [ ] `make test` and `make desktop-conformance` exit 0; new scan runs as
      part of `make desktop-conformance` or a new dedicated target
      referenced from it.

**Dependencies.** desktop-distribution-e4, desktop-distribution-m5,
desktop-distribution-m6 (needs the real desktop-child entry point and
`DESKTOP_SUPERVISOR_BIN`/fixture-sidecar build machinery already shipped
by m5/m6).

**Complexity.** M (widest uncertainty of the three — greenfield `.spec`
authoring; treat estimates conservatively, see Blocker 5's LOC note).

**Specialist suggestion.** `security-reviewer`, `determinism-reviewer`.

### desktop-distribution-m8 — Native-library consolidation and real BGE-M3 exercise in the packaged bundle

**Description.** Using m7's reproducible bundle, close the OpenMP
FAISS/Torch collision with an intentional, tested single-`libomp.dylib`
consolidation (not the accidental one PyInstaller's default collection
currently produces), and add a real-model gate that boots the desktop
child with an EXTERNAL HuggingFace cache, encodes a golden input set
through the real BGE-M3 and BGE-reranker-v2-m3 weights, and asserts
vector-level correctness — proving both that no model ships inside the
bundle and that the loaded weights actually produce correct output, not
merely that loading succeeded.

**Acceptance criteria.**
- [ ] Exactly one `libomp.dylib`-family file exists anywhere in the
      frozen bundle's `_internal/` tree (or equivalent PyInstaller
      collection root), asserted by an automated filesystem scan, not by
      manual `otool` inspection.
- [ ] Launching the frozen bundle (via `tools/desktop_sidecar_spike.py`'s
      `launch_environment`, which already forbids `KMP_DUPLICATE_LIB_OK`)
      and running a real FAISS `IndexFlatL2.add`+`search` call followed by
      a real multi-threaded Torch tensor operation in the SAME process
      exits 0 — the regression must reproduce the documented SIGABRT
      (exit 134) as its RED state before the fix, per this brief's
      confirmed repro.
      Verified.
- [ ] `KMP_DUPLICATE_LIB_OK` remains absent from every desktop launch
      environment (already enforced by `FORBIDDEN_ENV`; this AC re-asserts
      it under the new compute-path test, closing the gap that the
      existing guard only proves the env var wasn't SET, not that no
      collision exists).
- [ ] Booting the real desktop child (not the fixture sidecar) with
      `ARXMCP_ENABLE_RERANK=1` and an external HF cache directory, then
      encoding a fixed golden-string set through BGE-M3 and the reranker,
      produces vectors matching a committed golden fixture within a tight
      numeric tolerance (extends `tests/test_query_encoder.py`'s existing
      `ARXMCP_RUN_REAL_BGE_M3` golden-vector pattern to the desktop
      launch path).
- [ ] No model weight file (`.bin`, `.safetensors`, or HF cache blob) is
      present anywhere under the read-only application bundle tree —
      asserted by a path-containment check inverting
      `tools/desktop_sidecar_spike.py:validate_frozen_paths`'s existing
      "nothing escapes the bundle" logic to "the model directory is never
      inside the bundle."
- [ ] `make test` and `make desktop-conformance` exit 0; new marker
      (e.g. `requires_bundled_model`) registered in `pyproject.toml`
      following the exact `requires_desktop_stack` zero-skip pattern in
      `tests/conftest.py:43-88` (both a marker AND an env var required;
      collection-time enforcement, not a per-test `skipif`).

**Dependencies.** desktop-distribution-m7.

**Complexity.** M.

**Specialist suggestion.** `security-reviewer`, `determinism-reviewer`.

---

## Sequencing

**m7 before m8, strictly.** m8's ACs are all "run this check against the
frozen bundle" — without m7's committed, buildable `.spec`, there is no
bundle to check anything against. m7 does not depend on m8's findings.

Both m7 and m8 are independent of the two out-of-scope blockers
(macOS-14 floor, Developer ID signing) and should not block on them; the
e4 epic's OTHER agents can proceed on those blockers in parallel with
m7/m8, since a bundle can be built, hygiene-checked, and functionally
proven correct on this macOS 26.6 host with an ad-hoc signature — exactly
what spike-1 already did once. m7/m8 do NOT need Developer ID credentials
to complete; they inherit spike-1's ad-hoc-signing precedent
(`.claude/notes/spikes/desktop-distribution-spike-1.md:31`).

---

## Alternatives considered

- **One combined milestone (m7) for all three blockers.** Rejected: the
  brief's own effort estimates put the combined LOC at ~650–1,120 across
  Blockers 1+2+5, which is close to the milestone-pipeline's 800-LOC
  soft-abort threshold that m4's split (into m5/m6) already hit and was
  explicitly split to avoid (`plans/desktop-distribution-roadmap.md:248-259`,
  the m4 delivery note). Splitting on the "enabler vs. consumers" seam
  (spec-authoring vs. bundle-level proofs) mirrors that precedent.
- **Three separate milestones, one per blocker.** Rejected: Blocker 1 and
  Blocker 2 are both "add a permanent regression gate against the m7
  bundle" — same shape of work, same bundle dependency, no meaningful
  independent-shippability gap between them (neither is independently
  release-relevant without the other; shipping m7+Blocker1-only or
  m7+Blocker2-only leaves the desktop artifact equally not release-ready).
  Combining them keeps milestone count matched to the roadmap's existing
  M-sized granularity (m1–m6 precedent) rather than proliferating thin
  milestones.
- **Fold Blocker 5 into m5/m6 retroactively (amend already-shipped
  milestones).** Rejected: m5/m6 are already delivered and closed per the
  roadmap; amending shipped milestones violates the pipeline's forward-
  only delivery model and there is no live branch to extend.
- **Ship the OpenMP fix as `KMP_DUPLICATE_LIB_OK=TRUE` in the desktop
  launch environment.** Rejected explicitly by spike-1
  (`.claude/notes/spikes/desktop-distribution-spike-1.md:40,53`) and by
  the milestone brief — it silently permits wrong numeric results rather
  than fixing the duplicate-runtime root cause, and
  `tools/desktop_sidecar_spike.py`'s `FORBIDDEN_ENV` already codifies the
  prohibition.
- **Bump `BGE_M3_COMMIT_SHA` to a safetensors-bearing revision as part of
  Blocker 2.** Rejected: `ingest/embedder.py:339-353`'s existing comment
  and the E13_S10 issue explicitly scope that out (forces a corpus-wide
  MVCC re-embed, unrelated to desktop packaging). Blocker 2 is a bundling-
  and-correctness proof, not a model-pin bump.

---

## What CANNOT be honestly claimed after m7 + m8

- **Not release-ready.** Blockers 3 (macOS-14 floor) and 4 (Developer ID
  signing/notarization/stapling/Gatekeeper) remain open and gated on
  external prerequisites this research explicitly excludes (no Developer
  ID cert exists on this host — only an Apple Development cert). Neither
  m7 nor m8 produces a bundle that has been built, tested, or run on
  macOS 14, nor one that has passed Gatekeeper under a real Developer ID
  signature. Any milestone-completion messaging must say "three of five
  spike-1 blockers closed" — never "desktop release-ready" or "e4
  complete."
- **Not proven on Intel or any non-arm64 architecture.** All evidence
  here (native library inventory, OpenMP repro, bundle builds) is arm64-
  only, mirroring spike-1's own scope limit.
- **Not proven under a cold HuggingFace cache.** m8's real-model AC is
  satisfiable with THIS host's warm 20 GB cache; a genuinely cold-cache
  first-run download path (network failure handling, partial-download
  resume, disk-space preflight) is a distinct, unaddressed concern e3
  (first-run operator journey) may already own — do not claim m8 proves
  first-run download behavior.
- **Not a full packaging-hygiene audit.** The `direct_url.json` finding
  and the "single leaking file in the wheel" result are specific to THIS
  build's toolchain (`uv build`) and THIS install method (`pip install
  <local-path>`); a different build backend or an index-installed wheel
  could leak build-root strings through a different mechanism (e.g. a
  `setup.py`-based sdist embedding `__file__`-derived constants). m7's
  recursive scanner is the durable mitigation; the specific finding above
  is illustrative evidence, not an exhaustive enumeration.
- **`freeze_support()` behavior on the REAL entry point is unverified.**
  This research confirmed `freeze_support()` exists in the disposable
  spike script (`tools/desktop_sidecar_spike.py:176`) but did NOT read
  `server/desktop_child.py` (m5's real production entry point) to confirm
  it also calls it first. Flag this as an open discovery item for m7, not
  a closed fact.
