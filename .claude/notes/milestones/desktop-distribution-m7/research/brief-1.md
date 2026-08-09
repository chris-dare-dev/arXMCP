# Research brief — desktop-distribution-m7 (explore)

Reproducible PyInstaller bundle + packaging hygiene. Greenfield: no `.spec`
file exists anywhere in the tree, PyInstaller is not installed, not locked,
and not referenced in any doc/CI file. This brief maps exactly what m7 must
build versus reuse.

## 1. Entry point — `server/desktop_child.py` does NOT call `freeze_support()`

Confirmed by full read of `server/desktop_child.py` (395 lines) and by
`grep -rn "freeze_support" --include="*.py" .` (excluding `.venv/`): the ONLY
hits are `tools/desktop_sidecar_spike.py:176` (inside `main()`, before
`argparse`) and its test `tests/test_desktop_sidecar_spike.py:83-90`. The
real production entry point's `main()` (`server/desktop_child.py:335-386`)
starts directly with `logging.basicConfig(...)` — no `multiprocessing`
import at all in the file. This is a genuine gap, not a rediscovery: the
e4-blocker-research doc flagged it as unverified and it is now confirmed
missing.

**Where it must go:** first statement inside `main()` at
`server/desktop_child.py:336`, before `control_stream = sys.stdin.buffer`.
macOS defaults to the `spawn` start method (not `fork`), which is exactly
the case `freeze_support()` guards — a frozen `spawn`-based child
re-executes the frozen executable from the top; without the guard a
child process would re-enter `main()` and re-run the stdio control-frame
protocol, corrupting the parent's control stream. This module has no
`multiprocessing.Process`/`Pool` call itself, but `uvicorn`/`asyncio`
event-loop internals and any downstream library (torch, faiss) may spawn
worker processes, so the guard is required regardless of whether this
module invokes `multiprocessing` directly — PyInstaller's own docs make it
unconditional for any frozen Windows/macOS `spawn` entry point.

## 2. `latex2mathml/unimathsymbols.txt` — located, sized, wired

- File: `.venv/lib/python3.12/site-packages/latex2mathml/unimathsymbols.txt`,
  216,334 bytes (confirmed via `ls -la`).
- Read path: `server/handlers/equation.py:37`
  (`from latex2mathml.converter import convert as latex2mathml_convert`),
  invoked at `server/handlers/equation.py:244`
  (`mathml = latex2mathml_convert(latex)`). This is a live query-time code
  path (`server/handlers/equation.py:10` docstring), not a dev utility —
  every query-time LaTeX equation search goes through it.
- PyInstaller's default module-scanning does NOT collect this file (it is
  package data, not a `.py` module) — this is the exact gap spike-1's ADR
  recorded as its one bounded spec correction
  (`.claude/notes/spikes/desktop-distribution-spike-1.md:23`).
- Fix shape: a project-owned `hook-latex2mathml.py` using
  `PyInstaller.utils.hooks.collect_data_files` (no upstream
  `pyinstaller-hooks-contrib` hook exists for this narrow academic-math
  package — confirmed by the e4-blocker-research doc's search). ~10-15 LOC.
- **Provable, not assertable, test:** `tests/test_equation_latex_route.py`
  already has real LaTeX fixtures and asserts `"latex2mathml" in
  out["query_conversion"]["converter"]` (line 134) plus edge-case behavior
  (leaky `&`, bare backslash) — reuse this file's fixture LaTeX strings.
  The m7 AC ("byte-identical to the source tree conversion") should call
  `latex2mathml.converter.convert(fixture_latex)` once in the frozen
  bundle's Python (via a subprocess launched with
  `launch_environment`/`validate_frozen_paths`) and once in the source
  tree's own `.venv`, then assert the two MathML strings are byte-equal —
  not merely that `convert()` didn't raise. An import-only test would pass
  even if the hook shipped a truncated or wrong-version
  `unimathsymbols.txt`, since `latex2mathml.converter` degrades silently on
  missing symbol entries rather than raising.

## 3. `direct_url.json` — reproduced, exact contents, exact fix

The e4-blocker-research doc already built the real wheel and reproduced the
leak directly:
```
$ cat arxmcp-0.1.0.dist-info/direct_url.json
{"archive_info": {...}, "url": "file:///tmp/arxmcp-wheel-check/arxmcp-0.1.0-py3-none-any.whl"}
```
Confirmed `grep -rl "/tmp/arxmcp-wheel-check"` across the entire installed
site-packages tree returns exactly this one file — the wheel-install layer
is otherwise clean. "Sanitized" must mean precisely: either the file is
absent from the frozen bundle's `dist-info`, or its `url` field is
rewritten to a synthetic/generic value (e.g. `"url":
"file:///arxmcp-installed"` or dropped entirely) — with a test asserting no
`file://` URL anywhere in the frozen bundle's `dist-info/direct_url.json`
points at anything under the build host's temp root or `$HOME`. This is a
narrow, mechanical post-install/pre-freeze (or post-freeze) rewrite step,
not a broad packaging audit — confirmed as the ONLY leak at the wheel
layer. PyInstaller's own Analysis/collection step is the second, unmeasured
place a build-root string could leak (see §4).

## 4. Build-root leakage inventory — reachable vs. measured

| Vector | Reachable? | How a scanner detects it |
|---|---|---|
| `direct_url.json` (wheel dist-info) | Yes — measured, confirmed (§3) | grep bytes for build temp-root prefix |
| `.pyc` `co_filename` | Unmeasured — PyInstaller's Analysis step DOES embed build-machine absolute source paths into compiled bytecode unless stripped (flagged by e4-blocker-research as an open discovery item, not yet built/checked on this host since no `.spec` exists) | must assert explicitly, not assume absent — decompile/inspect `co_filename` via `dis`/`marshal` or grep raw bytes (co_filename strings are embedded as plain UTF-8 in the `.pyc`, so a byte-level grep across ALL regular files including `.pyc` — which the AC explicitly calls out — catches this without needing bytecode introspection) |
| `RECORD` (wheel metadata) | Wheel-only, not shipped into a PyInstaller onedir bundle (PyInstaller does not preserve `dist-info/RECORD`) — low relevance to the frozen artifact but worth a quick presence check | grep if present |
| `__pycache__` | PyInstaller's default collection compiles to `.pyc` inside its own archive/`_internal` tree, not raw `__pycache__` dirs from the source venv — should not appear if the build sources from a clean wheel install rather than an editable checkout | scanner should assert zero `__pycache__` directories in the frozen tree as a build-hygiene signal |
| Mach-O `LC_RPATH`/install names | Spike-1 measured these are relative (`@loader_path`, `@rpath`) with zero unresolved or non-system absolute dependencies (ADR line 29) — this vector is closed by PyInstaller's own relocation logic, not build-root-path-bearing | `otool -L`/`otool -l` sweep, already proven clean once; m7's scanner should still assert this per-build since it's cheap and regression-worthy |
| `.dist-info` metadata (`METADATA`, `WHEEL`) | Static text, does not embed build paths by construction (setuptools writes these from `pyproject.toml`, not from `sys.argv`/`__file__`) | low-risk, include in the same recursive grep for completeness/cheapness |

**The recursive scanner is the durable mitigation** — a byte-level grep
across every regular file in the frozen bundle for the build host's temp
root prefix (e.g. `/private/tmp`), `$HOME` prefix, and the invoking
username. `tools/wheel_install_check.py` has no existing string-scan
utility to reuse directly, but its `filesystem_metadata_manifest`
(`tools/wheel_install_check.py:477-518`) and `_sha256_file`
(`tools/wheel_install_check.py:469-474`) establish the project's existing
pattern for walking a tree and hashing/inspecting regular files — the new
scanner should follow that shape (sorted `rglob`, skip symlinks/dirs,
open regular files in binary mode) rather than inventing a new walking
convention.

## 5. Determinism — what's inherently non-deterministic in a PyInstaller `onedir` build

Unmeasured directly on this host (no `.spec` exists to build twice yet),
but knowable from PyInstaller's documented and widely-reported behavior,
which the implementer must verify empirically once the spec exists:

- **`.pyc` header timestamps/hashes** — Python's bytecode cache header
  embeds either an mtime+size pair or (with `SOURCE_DATE_EPOCH` /
  `PYTHONHASHSEED`-independent hash-based pycs) a content hash; PyInstaller
  compiles sources during Analysis, so unless the build pins
  `SOURCE_DATE_EPOCH` and disables mtime-based invalidation, two builds a
  few seconds apart can produce byte-different `.pyc` headers even for
  identical source. This is the single most likely "declared exception."
- **Archive/PKG ordering** — PyInstaller's `PKG`/`CArchive` internal
  ordering has historically depended on OS directory-listing order during
  collection (filesystem readdir order is not guaranteed stable across
  runs on some filesystems, though APFS on this host is typically stable
  within a single machine). Cross-run stability should still be verified
  empirically rather than assumed.
- **Embedded absolute paths** — PyInstaller's bootloader and `_internal`
  Analysis metadata can embed the build's own working-directory path in
  some diagnostic/warning strings even without a `co_filename` leak;
  covered by §4's byte-scan regardless of source.
- **Signature/codesign timestamps** — spike-1 ad-hoc-signed
  (`.claude/notes/spikes/desktop-distribution-spike-1.md:31`); ad-hoc
  signing has no secure timestamp, so this is not expected to add
  nondeterminism at m7's stage (real Developer ID timestamping, if added
  later, WOULD need its own exception).
- Random/UUID-based build IDs: PyInstaller embeds no random build UUID by
  default in `onedir` mode (unlike some `onefile` bootloader variants),
  but this must be verified against the specific 6.21.0 version pinned by
  spike-1 rather than assumed.

**AC1 implication:** the implementer should run the actual two-consecutive
build comparison as part of implementation (not assertable from research
alone) and enumerate the true exception set empirically — this section is
a prioritized hypothesis list, not a closed inventory. If `.pyc` timestamp
noise is confirmed, the "byte-identical manifest" comparison should either
(a) hash file contents after `SOURCE_DATE_EPOCH`-based `.pyc` normalization,
or (b) explicitly document `.pyc` files as an allowed-diff category in the
manifest comparison and prove the OTHER 5,530-ish regular files are
byte-identical — this decision is implementation-time, not research-time.

## 6. Reuse inventory — `tools/desktop_sidecar_spike.py`

Free for m7 to reuse as-is (no reinvention needed):
- `launch_environment()` (lines 19-44) — offline, sanitized, allowlisted
  env dict; already forbids `KMP_DUPLICATE_LIB_OK`/`PYTHONHOME`/
  `PYTHONPATH` via `FORBIDDEN_ENV` (line 16).
- `validate_launch_environment()` (47-57) — rejects ambient Python on PATH.
- `tree_manifest()` (60-74) — SHA-256 over mode+size+bytes+symlink-targets
  for every path; the direct extension point for AC1's "byte-identical
  manifest" comparison (the m7 brief text itself says "extends
  `tree_manifest`'s existing hash scheme").
- `tree_statistics()` (77-90) — regular-file/symlink/byte counts, does not
  follow symlinks.
- `validate_frozen_paths()` (93-99) — asserts `sys.executable`/`sys.path`
  entries stay inside the bundle; useful for m7's frozen-bundle Python
  invocation (§2, §5) launched as a subprocess.
- 90 lines of existing tests (`tests/test_desktop_sidecar_spike.py`) as the
  style precedent for new regression tests.

What m7 must build fresh (not present in the spike file):
- The `.spec` itself (`Analysis(scripts=[...])` pointed at
  `server/desktop_child.py`, or a wrapper script — the spike's own `main()`
  dispatches `serve`/`probe` modes and is explicitly "disposable"
  (docstring line 1); m7 should NOT extend the spike file into the
  production build target).
- `hook-latex2mathml.py` (§2).
- The `direct_url.json` sanitizer (§3).
- The recursive build-root scanner (§4).
- The `freeze_support()` fix to `server/desktop_child.py` (§1).
- The `make desktop-package` Makefile target.

**Is `tools/desktop_sidecar_spike.py` the right home for production code?**
No — its name and docstring ("Disposable frozen-sidecar entry point for
desktop-distribution-spike-1") and the `pyproject.toml:46` exclude rule
(`exclude = ["tools.desktop_lifecycle_spike*"]` — note this excludes a
DIFFERENT, similarly-named module `desktop_lifecycle_spike`, not
`desktop_sidecar_spike`; verify at implementation time whether
`desktop_sidecar_spike` is *also* excluded from the wheel or was simply
never gitignored from `tools*`'s inclusion glob — this needs one grep at
implementation time, flagged as open) both signal a throwaway artifact.
The `.spec`'s `Analysis(scripts=[...])` should point at
`server/desktop_child.py` (the real m5 entry point) directly, not at a
wrapper importing the spike module. The spike file's utility functions
(`tree_manifest`, `launch_environment`, etc.) are reusable as an imported
*library* from a NEW production location — the research task does not
mandate where that lives, but given `tools/` already hosts
`wheel_install_check.py` as a build/release-adjacent script, a new
`tools/desktop_package.py` (the scanner + build-driver script the e4
research doc names `desktop_package_scan.py`) is the natural home,
importing shared helpers from `tools.desktop_sidecar_spike` OR promoting
them into a shared non-spike module — implementation-time call, not
research-time.

## 7. The PyInstaller-dependency decision — recommendation

**Critical fact:** `.venv/bin/python -c "import PyInstaller"` raises
`ModuleNotFoundError` (verified live). `grep -n "pyinstaller" uv.lock
pyproject.toml` returns zero hits — it is not locked, not declared, not
referenced in any doc or CI file in the tree (`docs/`, `.gitlab-ci.yml`,
`ci-cd-templates/` all grep-clean for "PyInstaller"/"desktop-package").

**Existing repo precedent for exactly this shape of decision** — MinerU
(`pyproject.toml:325-333`, `docs/install.md:111-141`): a heavy,
dependency-tree-polluting tool (MinerU caps `transformers` at v4, which
would silently downgrade the BGE-M3/reranker stack) is deliberately kept
OUT of `pyproject.toml` entirely. It is installed into a **separate venv**
(`~/venvs/mineru/`), invoked via an absolute-path env var
(`ARXMCP_MINERU_BIN`), and gated in tests by a `requires_mineru` marker +
opt-in `ARXMCP_RUN_REAL_MINERU=1` env var, following the SAME zero-skip
collection-time enforcement pattern as `requires_desktop_stack`
(`tests/conftest.py:43-88`, cited by the e4-blocker-research doc for
Blocker 2's model-gating reuse too).

**Recommendation: mirror the MinerU pattern for PyInstaller.** Do NOT add
`pyinstaller`/`pyinstaller-hooks-contrib` to `pyproject.toml`
`[project.optional-dependencies]` or any dependency group that
`wheel-check`/`wheel-check-full` would resolve. Reasons:
1. PyInstaller and its hooks-contrib package are build-time-only tooling
   with their own dependency footprint (macholib, altgraph, pefile-family
   deps on other platforms) that has nothing to do with what
   `arxmcp-server`/`arxmcp-shim` need at runtime — adding it to the
   project's own dependency surface would make `make wheel-check-full`
   resolve PyInstaller into the "real deps" venv it's asserting a CLEAN
   operator install against, which is a category error: PyInstaller
   builds the wheel's *consumer* (the desktop bundle), it is not a runtime
   dependency of the wheel itself.
2. `uv.lock` discipline (per spike-1's own pinned-experiment section,
   `.claude/notes/spikes/desktop-distribution-spike-1.md:11-17`) already
   established a precedent of pinning PyInstaller by wheel SHA-256 in a
   throwaway staging environment, NOT via `uv.lock` — this is consistent
   with treating it as build tooling, not a project dependency.
3. A `dependency-groups` (PEP 735) entry (this project doesn't currently
   use one — only `[project.optional-dependencies]` `dev`) would be a
   plausible alternative to a separate venv, IF the team wants
   `uv run --group build` reproducibility instead of a manually-managed
   venv + pinned wheel SHA. This is the one place worth flagging as a
   genuine open call for Phase 2, since it differs from the MinerU
   precedent (separate venv, no lock) but stays within `uv`'s own tooling
   rather than a bespoke shell script.

**Recommended concrete mechanism:** a new `make desktop-package` target
that (a) provisions or reuses a dedicated build venv (e.g.
`.venv-pyinstaller/`, analogous to `~/venvs/mineru/` but project-local
since PyInstaller must run against the SAME site-packages the frozen app
ships — unlike MinerU, PyInstaller needs to `import` every runtime
dependency (`torch`, `faiss`, `lancedb`, etc.) to analyze their extension
modules, so it cannot be a fully independent venv; it must be layered ON
TOP of (or `uv pip install`ed into a clone of) the project's real runtime
venv, then have `pyinstaller`+`pyinstaller-hooks-contrib` added on top of
that clone) with PyInstaller pinned by wheel SHA-256 (mirroring spike-1's
own pin discipline) in a documented `docs/releasing.md`-adjacent doc, NOT
in `uv.lock`. This directly affects `wheel-check`: `wheel-check` and
`wheel-check-full` must NOT change at all (they test the *wheel*, not the
desktop bundle) — `desktop-package` is a separate, additive Makefile
target and CI job, consuming the wheel `wheel-check` already validates as
its `Analysis` input, not competing with it.

**Consequence to flag explicitly for Phase 2 sizing:** provisioning a full
PyInstaller build venv (uv-installing the ~2GB torch/faiss/lancedb runtime
stack PLUS PyInstaller/hooks-contrib on top) is itself a multi-minute,
multi-GB operation, comparable to `wheel-check-full`'s "~4 min warm,
~15 min cold" — this is separate from, and additive to, the ~74s build
time spike-1 measured for the PyInstaller `Analysis`+freeze step itself.

## 8. Per-AC provability

| AC | Provable how | Merely-assertable risk |
|---|---|---|
| AC1 (deterministic onedir, byte-identical manifest, 2 builds) | Build twice, diff `tree_manifest()` output (already hash-based); MUST empirically discover and document the true non-deterministic exception set (§5) — do not pre-assume `.pyc`-only | Risk: declaring an exception list without ever observing a real diff is assertion, not proof — the implementer must actually run two builds and inspect the diff |
| AC2 (latex2mathml byte-identical conversion) | Byte-compare `convert()` output between source-tree `.venv` and frozen-bundle subprocess on the SAME fixture LaTeX strings reused from `tests/test_equation_latex_route.py` | Risk (flagged in e4-blocker-research and repeated here): an import-only or "no exception raised" test does NOT discriminate — `latex2mathml` degrades silently on a missing/truncated symbol table rather than raising |
| AC3 (`freeze_support()` first statement + no duplicate spawn) | Static line-position check (first line of `main()`) PLUS a dynamic test launching the frozen executable and asserting no duplicate top-level process/log line appears — `server/desktop_child.py` currently has ZERO multiprocessing import, confirmed above; this is real, uncontested work | Low risk — the static-check half is trivially provable; the dynamic half needs the actual frozen executable, which requires §7's build venv decided first |
| AC4 (`direct_url.json` sanitized) | Grep the frozen bundle's `dist-info/direct_url.json` for any `file://` URL containing the build host's temp-root/HOME/username; §3 already proves the pre-fix content exists to sanitize | Low risk — narrow, already-measured leak |
| AC5 (recursive build-root scan across all regular files incl. `.pyc`) | Byte-level grep across every regular file (§4); the `.pyc` `co_filename` claim is UNMEASURED on this host — must actually build once and grep before claiming it's absent or present | Risk (explicitly called out in the AC text itself): "assert this explicitly rather than assuming `co_filename` is absent" — the research found NO existing measurement of this on a real PyInstaller build; it is a discovery item, not settled |
| AC6 (`make test` + `make desktop-conformance` exit 0) | Mechanical — run both after the new Makefile target lands; `desktop-conformance` (Makefile:156-164) currently has no PyInstaller-bundle step, so m7 either adds a step there or leaves `desktop-conformance` untouched and adds a parallel `desktop-package-check` referenced elsewhere; the e4-research doc's "What must be true" section explicitly allows either shape | Low risk, purely mechanical once the other 5 land |

## 9. Affected files — estimated LOC delta

| File | Change | Est. LOC |
|---|---|---|
| `server/desktop_child.py` | Add `multiprocessing.freeze_support()` as first `main()` statement + `import multiprocessing` | 2-3 |
| New `.spec` file (e.g. `packaging/arxmcp-desktop.spec` or repo-root) | `Analysis(scripts=["server/desktop_child.py"], ...)`, `EXE`/`COLLECT` for onedir, hook path wiring | 60-120 |
| New `packaging/pyinstaller-hooks/hook-latex2mathml.py` (or inline `datas=`) | `collect_data_files("latex2mathml")` | 10-15 |
| New `tools/desktop_package.py` (build driver + scanner, promoted from spike helpers) | Wraps venv provisioning, PyInstaller invocation, `direct_url.json` sanitizer, recursive build-root scanner, `tree_manifest` reuse | 200-320 |
| New `tests/test_desktop_package.py` (or similarly named) | AC1 two-build diff, AC2 byte-compare, AC3 freeze_support dynamic launch, AC4/AC5 scanner assertions | 180-280 |
| `Makefile` | New `desktop-package` target (+ possibly a `.PHONY` line, help text, and a `desktop-conformance` hook-in per AC6) | 15-30 |
| `docs/releasing.md` (or new `docs/desktop-packaging.md`) | Document the PyInstaller pin-by-SHA mechanism (§7), build venv provisioning, exception list from §5 once measured | 40-80 (docs, not code — separate from the LOC-cap gate per repo convention) |
| `pyproject.toml` | Possibly a comment-only note mirroring the MinerU block (§7) explaining why PyInstaller is NOT a project dependency — no functional change if the separate-venv recommendation is taken | 0-10 |

**Total estimated code LOC: ~465-740** (excludes docs). This lands inside
the e4-blocker-research doc's own "~250-420" estimate for Blocker 5 alone,
but that estimate predates confirming `freeze_support()` is fully absent
(cheap) and predates sizing the new `tools/desktop_package.py` build-driver
script as its own file rather than inline `.spec` code — the wider range
here reflects that once-inline logic (venv provisioning, scanner) is
better factored as a testable module. Treat the upper end as live risk:
if PyInstaller's `.spec` hook-writing proves fragile (the OpenMP
consolidation concern from Blocker 1, though that's m8's scope, hints
hooks-contrib versioning is a real source of surprise), this could grow.
This is comfortably under the pipeline's 800-LOC soft-abort threshold
the e4-blocker-research doc cites, but not by a wide margin — Phase 2
should treat the upper bound as real, not decorative.

## 10. Build cost (AC1 requires two consecutive builds)

- Per-build wall-clock: spike-1 measured 74.04s for the `Analysis`+freeze
  step itself on this exact host/toolchain (PyInstaller 6.21.0, same
  Python 3.12.13, same macOS 26.6 arm64) — a reasonable baseline for m7's
  first build; the SECOND build (needed for AC1's diff) should be similar,
  assuming no cache/staleness effects PyInstaller doesn't already handle.
  Budget ~150-180s combined for the two builds alone, plus manifest-hash
  computation over ~5,530 files each (`tree_manifest`'s streaming SHA-256
  is not free at ~760MB of regular-file bytes per build — expect single-
  digit seconds per hash pass on this host, not measured precisely).
- Per-build disk: 759,839,270 regular-file bytes / 772,259,840 allocated
  bytes measured by spike-1 for ONE onedir tree. Two consecutive builds
  (unless the second overwrites the first in place, which AC1's diff
  needs to be careful about — comparing "old build" vs "new build" of the
  SAME target path is fine, but if the harness wants both trees on disk
  simultaneously for comparison, budget ~1.5GB).
- **This does not include §7's build-venv provisioning cost**, which is a
  separate, likely-larger, one-time-per-session cost (comparable to
  `wheel-check-full`'s multi-minute dependency resolution) — the two
  costs are additive but distinct: provisioning happens once per session/
  CI run, the two builds happen every `make desktop-package` invocation.

## 11. Prior art in this repo — summary

- `.claude/notes/spikes/desktop-distribution-spike-1.md` — the ADR, all
  measured baselines cited throughout this brief.
- `.claude/notes/spikes/desktop-distribution-e4-blocker-research.md` —
  Blocker 5's prior analysis; this brief confirms/extends it with live
  greps and file reads rather than repeating it. Where this brief disagrees
  or adds new measurement (freeze_support absence confirmed as fact rather
  than "unverified"; MinerU precedent surfaced for the PyInstaller-
  dependency decision; §4/§5's expanded leakage/determinism tables), that
  is new information for Phase 2.
- `tools/desktop_sidecar_spike.py` + `tests/test_desktop_sidecar_spike.py`
  — reuse inventory, §6.
- `server/desktop_child.py` — the real entry point, §1.
- `server/handlers/equation.py:37,244` — the `latex2mathml` call site, §2.
- `tools/wheel_install_check.py:469-518` — existing tree-walk/hash pattern
  to follow for the new scanner (§4), and `wheel-check`/`wheel-check-full`
  targets (`Makefile:446-473`) that m7 must NOT modify or compete with
  (§7).
- `pyproject.toml:320-333` — MinerU's separate-venv precedent, directly
  informing §7's recommendation.
- `Makefile:156-164` — `desktop-conformance` target, the likely hook point
  for AC6.

## 12. Relevant Nalej MCP context

Not applicable — this is an arXMCP-repo-local milestone (Python desktop
packaging for a Claude MCP server product), not a Nalej platform GitOps/
Kubernetes change. The Nalej platform-knowledge MCP tools (chart context,
ops references, environment maps) have no relevant surface here; skipped
per the task's actual domain. No `lessons.md`/Nalej-memory entries apply.

## 13. Existing skills/agents that could implement this

None of the Nalej-workspace platform skills/agents apply (this is not a
Kubernetes/ArgoCD/Terraform change). Within this repo, the milestone
brief's own specialist suggestions — `security-reviewer` (build-root
leakage, `direct_url.json` sanitization has security-adjacent provenance
implications) and `determinism-reviewer` (AC1's core concern) — are the
right Phase-2/Phase-3 specialist dispatch, per the milestone's own
metadata. No dedicated "packaging" or "PyInstaller" specialist exists in
this repo's tooling.

## 14. External sources reviewed

None fetched this session — the milestone is fully answerable from
in-repo evidence (the prior spike, the prior blocker-research doc, and
live greps/reads of the actual source tree). PyInstaller's own hook-writing
conventions (`collect_data_files`, `Analysis(datas=...)`) are referenced by
name from the already-cited e4-blocker-research doc's prior investigation;
re-fetching PyInstaller's upstream docs was not necessary to answer this
brief's scope and was skipped to stay inside the research budget. Phase 2
implementation should consult PyInstaller 6.21.x's own hook-writing guide
(https://pyinstaller.org/en/v6.21.0/hooks.html) directly when authoring
`hook-latex2mathml.py`, since exact API surface (e.g. `hiddenimports` vs
`datas` return shape) is version-specific and best read at implementation
time, not paraphrased here.

## 15. Recommended approach (≤500 words)

Land `.spec` authoring, the `latex2mathml` hook, `direct_url.json`
sanitization, the build-root scanner, and the `freeze_support()` fix
together, in that rough dependency order, since the scanner and manifest-
diff tooling both need a real buildable bundle to run against.

1. **Fix `server/desktop_child.py` first** (§1, ~3 LOC) — add
   `import multiprocessing` and `multiprocessing.freeze_support()` as the
   first statement in `main()`. Trivial, unblocks nothing else but is
   cheap and independently correct regardless of build tooling.
2. **Decide the PyInstaller provisioning mechanism** (§7) before writing
   the `.spec` — recommend a project-local build venv layered on top of
   the real runtime dependency set, with PyInstaller pinned by wheel
   SHA-256 in a documented location, NOT added to `pyproject.toml`'s
   resolvable dependency set and NOT touching `uv.lock`. Mirrors the
   MinerU precedent exactly.
3. **Author the `.spec`** pointing `Analysis(scripts=[...])` at
   `server/desktop_child.py`, reusing `tools/desktop_sidecar_spike.py`'s
   proven `launch_environment`/`validate_frozen_paths`/`tree_manifest`
   helpers as an imported library (promote to a non-spike-named shared
   module if the spike module turns out to be wheel-excluded — verify at
   implementation time per §6's flagged open item).
4. **Add `hook-latex2mathml.py`** using `collect_data_files("latex2mathml")`.
5. **Add the `direct_url.json` sanitizer** as a post-install (before
   PyInstaller `Analysis`) or post-freeze (scanning the bundle's
   `dist-info`) step — either works given the leak is confirmed to
   originate at wheel-install time, not during freezing.
6. **Build the new `tools/desktop_package.py`** driver: provisions/reuses
   the build venv, runs PyInstaller, runs the sanitizer, runs the
   recursive build-root scanner (grep bytes for temp-root/HOME/username
   across every regular file including `.pyc`), and exposes a
   `tree_manifest`-based two-build diff for AC1.
7. **Wire `make desktop-package`** into the Makefile, and hook a scan/
   conversion step into `make desktop-conformance` or a sibling target per
   AC6.
8. **Write the regression tests** (`tests/test_desktop_package.py` or
   similar) covering AC1-AC5 concretely per §8's provability table —
   critically, the AC1 exception list and the AC5 `.pyc` co_filename
   question can only be answered by actually building once and observing,
   not by pre-writing assertions from this research alone.

Budget the first real build+diff cycle as a discovery step inside Phase 2,
not a known quantity — §5 and §8 are explicit about what remains
unmeasured until a `.spec` exists to build from.

## 16. Alternatives considered

- **Add PyInstaller to `pyproject.toml` as a `dev`/`build` optional
  dependency.** Rejected: pollutes `wheel-check-full`'s "real operator
  deps" resolution with build-only tooling; breaks the category
  distinction between "what ships to operators" and "what builds the
  desktop artifact"; contradicts the MinerU precedent this repo already
  established for exactly this shape of tooling.
- **Extend `tools/desktop_sidecar_spike.py` in place into the production
  build entry point.** Rejected: the file is explicitly named/documented
  as disposable spike code; the `.spec` should target the real
  `server/desktop_child.py` entry point directly, per the milestone's own
  description.
- **Skip the two-consecutive-build empirical determinism check and
  hand-write an assumed exception list (`.pyc` only) from general
  PyInstaller knowledge.** Rejected: AC1 explicitly requires the
  exceptions be "documented rather than silently ignored," which requires
  observing a real diff, not assuming one; general PyInstaller-ecosystem
  knowledge about nondeterminism sources is a hypothesis (§5), not a
  substitute for this repo's own measurement.
- **Fold the `direct_url.json` fix into `tools/wheel_install_check.py`
  instead of a new desktop-specific script.** Rejected: `wheel_install_check.py`
  tests the WHEEL as delivered to a Python-environment operator (pip
  install path); the desktop bundle's `direct_url.json` lives inside a
  frozen PyInstaller tree with a different install lineage (built from the
  wheel, then frozen) — conflating the two gates would make
  `wheel-check`/`wheel-check-full` (which spike-1 and this research both
  established must stay untouched) implicitly desktop-aware.

## 17. Risks and unknowns

- **`.pyc` `co_filename` embedding in a PyInstaller onedir build is
  UNMEASURED on this host** — the AC5 scan must actually confirm rather
  than assume; budget time for it to be a real finding requiring a fix,
  not a formality.
- **The true non-deterministic exception set for AC1 is UNMEASURED** —
  §5 is a hypothesis list built from general PyInstaller knowledge and
  spike-1's evidence, not from a real two-build diff on this exact `.spec`.
- **Whether `tools/desktop_sidecar_spike.py` is excluded from the built
  wheel is unverified** — `pyproject.toml:46` excludes
  `tools.desktop_lifecycle_spike*`, a DIFFERENTLY-named module; confirm at
  implementation time whether `desktop_sidecar_spike` is also
  wheel-excluded or ships in the operator wheel today (a pre-existing
  question, not introduced by m7, but relevant if m7 imports from it).
- **PyInstaller build-venv provisioning cost is additive to session/CI
  time** (§7, §10) — comparable to `wheel-check-full`'s multi-minute
  dependency resolution; Phase 2 should not assume this is "free" relative
  to the ~74s freeze step itself.
- **hooks-contrib version drift risk, flagged by the e4-blocker-research
  doc for Blocker 1 (OpenMP consolidation)** — m7 does not need to solve
  the OpenMP collision (that's m8), but the SAME hooks-contrib version
  sensitivity could affect how cleanly `collect_data_files` behaves for
  `latex2mathml` across PyInstaller/hooks-contrib version bumps; pin
  exactly (by wheel SHA-256, mirroring spike-1) rather than a loose range.
- **Sync-wave/GitOps/IRSA concerns are N/A** — this is a Python-repo-local
  build-tooling milestone with no Kubernetes/cross-cluster/IAM surface.
- **Conventional-commit + GPG signing** apply as usual per this repo's own
  git conventions (outside this brief's scope to restate).

## 18. External-write actions required

None. This milestone is entirely local build/test tooling within the
arXMCP repo — no `git push`, no MR, no ArgoCD sync, no AWS mutation is
implied by the research itself. The implementer's eventual commit+push (if
this repo follows the Nalej workspace's direct-to-`main` convention, or its
own repo-local convention — verify `arXMCP/CLAUDE.md`, not read in this
research pass since it's outside this milestone's explore scope) is the
only external write, and ordinary per the repo's existing workflow — no
new external-write surface is introduced by m7 itself.

## 19. Open questions for the user

None — the milestone brief and the two prior research artifacts
(spike-1 ADR, e4-blocker-research) are sufficient to scope Phase 2 without
further clarification. The one substantive open call (§7's "separate venv
vs. PEP 735 `dependency-groups`" choice) is flagged as a recommendation
with reasoning, not a blocking question — Phase 2 can proceed with the
separate-venv recommendation and revisit only if the implementer finds a
concrete reason `dependency-groups` is preferable once drafting the
Makefile target.
