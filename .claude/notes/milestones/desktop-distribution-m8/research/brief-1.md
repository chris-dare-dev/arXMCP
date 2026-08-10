# Research brief — desktop-distribution-m8 (agent: solo/general)

Fresh build performed at HEAD `07f8ac923a950dda8904126677eeb71a343574d5`
(2026-08-09), `make desktop-package`-equivalent
(`.venv/bin/python apps/desktop/pyinstaller/desktop_package.py build`),
75.83 s, clean (`5282 files scanned clean`, `report.json` hits: `{}`). All
findings below are measured against this exact bundle at
`var/desktop-package/dist/arxmcp-desktop-child/`, not the spike-1 artifact
(gone) and not the stale pre-existing `var/desktop-package/` tree from the
m7 rectify run.

## 1. TL;DR

**The headline finding overrides the milestone brief's own framing of AC2:
the real FAISS-add+search-then-Torch-inference collision does NOT reproduce
on the current, unmodified m7 frozen bundle** — confirmed three independent
ways (natural resolution, forced dual-load, heavy workload), while the
identical recipe against the unfrozen `.venv` crashes reliably (exit 134,
re-verified this session). AC1 (filesystem: "exactly one `libomp.dylib`")
is nonetheless genuinely RED today (2 distinct-content real files + 1
symlink) and is a real, provable, valuable fix — deleting the orphaned
`faiss/.dylibs/libomp.dylib` is the correct M8 scope regardless of AC2's
process-level ambiguity. **Main risk:** if the implementer builds AC2's
regression as "run the frozen bundle, expect a crash, fix it, expect
green" without first replicating this finding, they will spend the
milestone chasing a RED state that structurally does not exist, or worse,
paper over the gap by asserting the crash without ever having observed it.
**Backup plan:** design AC2 as two artifacts — (a) a permanent
filesystem-level single-file guard (genuinely RED→GREEN, cheap, high
confidence) and (b) a fault-injection process-level test that deliberately
forces the orphaned duplicate to be the one dyld resolves (proving the
crash mechanism is real and would fire if a future PyInstaller/hooks-contrib
version ever stops accidentally consolidating), rather than relying on the
natural build to demonstrate it.

## 2. Item 1 — Native-library inventory (measured, this build)

| # | Path (relative to `_internal/`) | Type | Size | SHA-256 (first 12) |
|---|---|---|---|---|
| 1 | `libomp.dylib` | **symlink** → `torch/lib/libomp.dylib` | — | — |
| 2 | `torch/lib/libomp.dylib` | regular | 856,096 B | `cc166d396332` |
| 3 | `faiss/.dylibs/libomp.dylib` | regular | 750,624 B | `798920 2b0c9f` (spike-1's `798920…` prefix matches) |

**Canonical copy: `torch/lib/libomp.dylib` (`cc166d…`)**, reached via the
top-level `_internal/libomp.dylib` symlink. **Redundant copy:
`faiss/.dylibs/libomp.dylib` (`798920…`)** — confirmed orphaned, not
canonical-by-accident-of-first-write: no Mach-O load command anywhere in
the 5,282-file bundle references it by path (`grep`-equivalent scan of
every `.so`/`.dylib`'s `otool -L` output for a literal `.dylibs/libomp`
load target returns only the file's own self-referential ID line).

**Why the redundant copy exists but is dead weight** — confirmed via
`otool -L` / `otool -l` on the real artifacts:

- `faiss/_swigfaiss.abi3.so`: `LC_LOAD_DYLIB @rpath/libomp.dylib` +
  `LC_RPATH @loader_path/..` → from `_internal/faiss/` that's `_internal/`
  → resolves to the `_internal/libomp.dylib` symlink → `torch/lib/libomp.dylib`
  (`cc166d…`). **Not** the fully-qualified
  `@loader_path/.dylibs/libomp.dylib` recorded for the *unfrozen* venv in
  `.claude/notes/spikes/desktop-distribution-e4-blocker-research.md:72` —
  PyInstaller's binary post-processing (`bindepend`/fixup) rewrites the
  fully-qualified relative dependency to `@rpath` during collection. This
  is the exact mechanism spike-1's ADR named ("PyInstaller's onedir
  collection step already accidentally consolidates the two dylibs into
  one shared copy at the bundle root").
- `torch/lib/libtorch_cpu.dylib`: `LC_LOAD_DYLIB @rpath/libomp.dylib` +
  `LC_RPATH @loader_path/../..` → from `_internal/torch/lib/` that's also
  `_internal/` → **same** symlink, **same** resolved file.

Both consumers therefore load the identical single `torch/lib/libomp.dylib`
image at runtime by construction of today's rpath chains. This is
accidental (nothing pins it — a hooks-contrib/PyInstaller bump or a
faiss-cpu wheel that reverts to a fully-qualified load path could silently
reintroduce a genuine second load), matching the risk
`desktop-distribution-e4-blocker-research.md:86-93` already flagged.

### Process-level verification (the load-bearing new evidence)

Ran the real FAISS `IndexFlatL2` add+search then real multi-threaded Torch
compute **against the actual frozen native libraries** (loaded the real
`_internal/faiss/_swigfaiss.abi3.so` directly via `importlib` — the raw
SWIG extension, not a mock — plus the real loose `torch/` tree under
`_internal/`, using `.venv/bin/python3` purely as the process driver; the
native `.dylib` bytes and their on-disk rpath chains are exactly what the
bootloader executable would load):

| Run | Recipe | Result |
|---|---|---|
| 1 | Natural resolution, spike-1-sized workload (100×4 FAISS + 64×512 matmul ×20) | **exit 0** |
| 2 | Same, but `ctypes.CDLL` force-loads the orphaned `faiss/.dylibs/libomp.dylib` FIRST with `RTLD_GLOBAL` before running compute | **exit 0** |
| 3 | Heavy workload (50,000×256 FAISS index + 2048×2048 matmul ×30, `torch.set_num_threads(8)`) | **exit 0** |
| sanity | Identical recipe (run 1's sizes) against the **unfrozen** `.venv` (same host, same session) | **exit 134**, `OMP: Error #15` — reproduced verbatim |

The sanity run rules out environment drift as the explanation for runs
1–3's silence. Diagnostic scripts are throwaway, in the scratchpad only
(`/private/tmp/.../scratchpad/frozen_omp_probe{,2,3,4}.py`), never written
to the repo.

**Conclusion carried into §3/§8: on THIS build, AC2's literal "must
reproduce the SIGABRT as its RED state" cannot be satisfied by running the
existing bundle as-is.** The collision is real (confirmed live in the
unfrozen venv, per the established facts and my own re-verification) but
is not currently observable in the packaged artifact.

## 3. Item 2 — Consolidation design

Recommend **Option A (spec-level exclusion), not `install_name_tool`
rewriting**:

- Add a `hook-faiss.py` (project-owned, same pattern/dir as the existing
  `hook-latex2mathml.py`) that returns an `excludedimports`/explicit
  binary-exclusion for `faiss/.dylibs/libomp.dylib` from `Analysis()`'s
  binary collection — PyInstaller's hook API supports excluding a specific
  collected binary via a hook's `datas`/`binaries` return combined with
  `Analysis(excludes=...)` is for *modules*, not binaries; the correct
  mechanism is a **post-`Analysis()` spec-level filter** on
  `child_analysis.binaries` / `probe_analysis.binaries` (a list of
  `(dest_name, src_path, typecode)` tuples) that drops any entry whose
  `dest_name` matches `faiss/.dylibs/libomp.dylib`, mirroring the existing
  `_sanitize_sysconfigdata` post-`Analysis()` mutation pattern already in
  `arxmcp_desktop.spec:96-107`. This is the SAME shape of fix already
  proven in this spec (mutate the `Analysis` object's TOC before `PYZ()`),
  not a new mechanism.
- **Do NOT use `install_name_tool` to rewrite `_swigfaiss.abi3.so`'s
  `LC_LOAD_DYLIB`.** It is unnecessary — the binary already resolves via
  `@rpath` correctly, per §2 — and it is exactly the risk the milestone's
  own item-2 prompt names for code-signing: rewriting a load command after
  ad-hoc signing invalidates that binary's signature hash, forcing a
  re-sign step to be inserted between the rewrite and
  `test_bundle_executables_exist_and_are_signed`
  (`tests/test_desktop_package.py:441-458`). Excluding the file from
  `Analysis().binaries` avoids touching any Mach-O load command at all —
  PyInstaller signs each collected binary once, at COLLECT time, after the
  TOC is final; dropping the entry from the TOC means it's simply never
  copied or signed, zero interaction with the signing step.
- **Ordering relative to signing (answering the milestone's explicit
  ask):** the exclusion must happen at the `Analysis()`/TOC-mutation stage
  — same phase as `_sanitize_sysconfigdata` and the PYZ `.pure.sort()`
  calls, i.e. `arxmcp_desktop.spec:96-137`, strictly BEFORE `PYZ()`/`EXE()`/
  `COLLECT()`. Ad-hoc signing happens automatically inside `COLLECT()`/
  `EXE()`'s codesign invocation and is scoped per-binary at that point — a
  binary excluded before then is never signed and never needs re-signing.
  This is also why Option A composes cleanly with the deferred Developer ID
  work (`desktop-distribution-e4` blocker 4): whatever signing identity
  that milestone plugs in, it signs whatever TOC this milestone leaves
  behind — no interaction between the two milestones' mechanisms.
- **Trade-off vs. Option B (dependency-side, bump faiss-cpu):** rejected
  for m8 for the same reason `desktop-distribution-e4-blocker-research.md:106-111`
  already gave — not guaranteed to exist, and even if a newer wheel drops
  the bundled `libomp.dylib`, the regression test below is still required
  regardless of which mechanism produces the single-file state. Revisit
  only if a future `faiss-cpu` bump is independently scheduled.
- **Test the exclusion drops the RIGHT file and doesn't break the LIVE
  one.** A fast unit test (parallel to
  `test_exception_set_is_closed_and_size_pinned`) should assert the spec's
  exclusion predicate matches `faiss/.dylibs/libomp.dylib` and does NOT
  match `torch/lib/libomp.dylib` or the top-level symlink target — a
  string-match bug here would silently drop the wrong (live) copy and
  break the bundle at first FAISS import.

## 4. Item 3 — The RED-state regression (revised design, per §2's finding)

**Two artifacts, not one — because no single test can be both a genuine
RED→GREEN proof AND a permanent regression on this exact library pair.**

### 4a. Filesystem-level single-file guard (genuinely RED today, GREEN after §3's fix)

Extend `scan_tree`-adjacent logic in `desktop_package.py` (or a small
dedicated function) to walk the bundle and assert exactly one regular file
matches `*/libomp.dylib` (symlinks don't count as extra copies; their
resolved target does). **Measured RED state today:** 2 regular files
(`torch/lib/libomp.dylib`, `faiss/.dylibs/libomp.dylib`). This is honest,
cheap (already have the file-walk machinery in `scan_tree`/`file_manifest`),
and requires no compute — pure filesystem assertion, matching the
milestone's own AC1 wording ("asserted by an automated filesystem scan,
not by manual `otool` inspection").

### 4b. Process-level ground truth — fault-injection framing, not natural-build framing

Since §2's finding rules out "just launch the natural bundle and watch it
crash," the honest regression needs an explicit BEFORE/AFTER pair:

1. **BEFORE (proves the mechanism is real on these exact binaries, not
   just historically true in the venv):** a test that deliberately
   restores the pre-consolidation state — either (a) re-adds the excluded
   `faiss/.dylibs/libomp.dylib` file back into a COPY of the bundle and
   rewrites `_swigfaiss.abi3.so`'s `LC_LOAD_DYLIB` in that copy to the
   fully-qualified `@loader_path/.dylibs/libomp.dylib` path (the pre-fix
   shape, via `install_name_tool` on a disposable copy — never the shipped
   artifact), then runs the real add+search+Torch recipe against that
   COPY and asserts exit 134/SIGABRT; or (b) build the bundle from a
   `.spec` variant with the exclusion hook disabled and run the same
   recipe. **(a) is cheaper** (no second full 75 s build) but needs proof
   that a rewritten-then-recomputed-checksum copy still triggers a REAL
   collision (my scratchpad experiments show that merely `ctypes.CDLL`
   force-loading the orphan alongside the natural resolution does NOT
   reproduce it — the crash needs the CONSUMING library's own load
   command to actually target the orphan, which is what the
   `install_name_tool` rewrite achieves and my dlopen-force test did not).
   **This BEFORE arm needs to be empirically validated by the implementer
   before committing to it as the milestone's RED-state evidence** — it is
   a design proposal, not something I could verify without writing new
   code into the repo (out of scope for a research-only pass).
2. **AFTER (the permanent regression, mirrors AC2's launch-environment
   discipline):** build the real spec (with §3's exclusion applied), launch
   the frozen executable via `launch_environment`-equivalent (forbidding
   `KMP_DUPLICATE_LIB_OK`, matching `tools/desktop_sidecar_spike.py:14-15,42-49`'s
   `FORBIDDEN_ENV` discipline), and assert exit 0 on the real
   add+search+Torch recipe. This is the test that runs in
   `make desktop-package-check` on every future build.

**Recommended implementation vehicle for the compute path itself:** a
THIRD PyInstaller-collected EXE (e.g. `arxmcp-desktop-omp-probe`), sharing
the same `COLLECT()` as `arxmcp-desktop-child`/`arxmcp-desktop-probe` —
mirrors the existing `probe_entry.py` precedent exactly
(`arxmcp_desktop.spec:126-150`). Its entry script does a NORMAL
`import faiss; import torch` (pulling the real `faiss/__init__.py` /
`faiss/loader.py` wrapper out of the PYZ, which my scratchpad diagnostics
deliberately bypassed via raw SWIG calls — production code never does
that, and a probe that hand-rolls SWIG is fragile across `faiss-cpu`
version bumps). This is preferred over my scratchpad's "external
interpreter pointed at the bundle's native files" technique for the
SHIPPED regression: it exercises the actual `faiss` import chain the
frozen server would use, and it needs no `.venv` interpreter present on a
verification-only machine — the whole point of `onedir` distribution.
Rejected: extending `server/desktop_child.py`'s real MCP `search_papers`
path as the compute trigger — it's an equally valid natural trigger (a
FAISS Tier-2 cache `add`+`search` fires from **`server/cache.py:900-908,950,1076-1084`**
on real query traffic, which IS the honest "production code path"
argument) but requires a seeded corpus, the full launch/readiness
handshake, and MCP request plumbing — much heavier than a dedicated probe
EXE for what is fundamentally a native-library-loading question. Note
this as a documented alternative in case the implementer wants the
strongest "real production path" framing instead of a synthetic probe;
either satisfies the AC's intent.

**Exit-code detection discipline (the milestone explicitly flags this
trap):** launch via `subprocess.run([exe], ...)` and read
`proc.returncode` directly — never through a shell pipeline (`sh -c "... |
..."`), where `$?` reflects the pipeline's last stage, not the crashing
child. `tests/test_desktop_package.py`'s existing
`test_frozen_spawn_reexec_never_reenters_main` already does this correctly
(`subprocess.run`/`subprocess.Popen` with `.returncode`, no `shell=True`,
no pipe) — follow that precedent exactly, not a new one. On macOS/Linux,
SIGABRT (signal 6) surfaces as `returncode == -6` when using `subprocess`
directly (Python maps a negative return to `-signal`), OR `134` if the
process is launched such that the shell's wait-status conversion applies
— assert on **both** `proc.returncode in (-6, 134)` unless empirically
pinned to one on this launch method (verify at implementation time; my
scratchpad's inline `python -c "..."` runs reported `EXIT CODE: 134`
because I invoked them through Bash's own `$?`, which IS shell-observed
exit status, not `subprocess.run`'s raw `returncode` — the two conventions
differ and the implementer must pick one and assert on it explicitly, not
assume they match).

## 5. Item 4 — The real-model gate

**Correction to the dispatch's framing:** there is no existing golden
*fixture file* to extend. `tests/test_query_encoder.py`'s
`TestFrozenVectorContract.test_frozen_vector_path_is_documented`
(lines ~786-804) is an intentionally EMPTY placeholder — its own docstring
says "We don't ship the golden vector here... this assertion keeps the gap
visible." No file exists at
`tests/fixtures/query_encoder/golden_v1.npy` (confirmed: `find
tests/fixtures -iname "*golden*"` → zero hits). The real precedent that
DOES exist and DOES work is narrower: `TestRealModelIntegration` (same
file, ~803-827) is a **self-consistency** check (two calls, same input,
cosine ≥ 0.9999 between them) — it never compares against a committed
external fixture. Similarly `tests/retrieval/test_rerank.py`'s
`TestOnPathRequiresModel` (~734-780) checks LATENCY (<5s for 50
candidates), not score correctness. **m8 must author the golden fixture
file from scratch** — this is real, uncounted work the milestone brief's
"extend the pattern" phrasing understates.

**Design:**

- Generate the golden fixture ONCE, out-of-band (a one-time script run,
  not part of the test suite, output committed as
  e.g. `tests/fixtures/desktop_model/golden_v1.json` — small, since it's a
  handful of fixed strings' 1024-dim vectors plus a few rerank scores, not
  the corpus).
- Fixed golden input set: reuse existing fixture strings already
  established elsewhere in the suite rather than inventing new ones (e.g.
  the reranker test's `"perverse sheaves on flag varieties"` query +
  `tests/test_query_encoder.py`'s `"Theorem 1: every group has identity."`)
  — keeps provenance traceable, avoids a second undocumented fixture
  corpus.
- **Tolerance:** `numpy.allclose(atol=1e-4)` matching
  `TestFrozenVectorContract`'s own commented-out intended usage
  (`tests/test_query_encoder.py:797`) — this is not arbitrary, it's the
  tolerance the codebase already picked for this exact model/precision
  combination and never shipped. Do not loosen it without a stated reason
  (float32 CPU inference on arm64 vs. whatever host generated the golden
  is the only legitimate source of drift at this tolerance).
- **Why loading weights ≠ correct output** (per the milestone's own
  framing): `AutoModel.from_pretrained(..., use_safetensors=True)` can
  silently fall back to `.bin` in some transformers versions even when
  weights are truncated (already the documented rationale for
  `assert_no_bin_in_snapshot`, `server/model_loader.py:135-192`) — a
  load-only check cannot distinguish correct weights from a partially
  corrupted or wrong-revision checkout. Only comparing actual encoder
  OUTPUT against a fixture proves the weights that loaded are the weights
  intended.
- **External-cache proof — cheaper than the milestone brief implies.**
  HF cache resolution is `$HF_HOME` env var, defaulting to
  `~/.cache/huggingface` (`server/model_loader.py:123-132`) — this is
  ALREADY outside any bundle path by construction; no desktop-specific
  wiring is needed to make the model load externally. The proof obligation
  is narrower than "wire an external cache" — it's "assert the frozen
  bundle's OWN tree contains zero `.bin`/`.safetensors`/HF-cache-shaped
  paths," inverting `tools/desktop_sidecar_spike.py:validate_frozen_paths`
  (lines 93-99) exactly as the blocker research already specified: walk
  `sys.path` entries plus check `HF_HOME` (or its default) resolves
  OUTSIDE `bundle.resolve()`.
- **Boot path — reuse `_child_env()`/`real_child` from
  `tests/test_desktop_child.py:111-117,242-291`, don't invent a new one.**
  That fixture already boots the REAL desktop child (not frozen, but the
  production entry point) with `ARXMCP_ENABLE_RERANK=1` and asserts
  `ready["warm"] == {"embedder": True, "lancedb": True, "reranker": True}`
  — this IS the "boot with rerank + external cache" precedent the item
  description references, just not yet extended to output-correctness
  assertions. Whether the new gate needs to run against the FROZEN
  executable (via `CHILD_ARGV` swapped for `bundle/arxmcp-desktop-child`)
  or the unfrozen child is a real design choice: the milestone's own AC5
  ("no model file under the bundle") only needs the FROZEN tree's
  filesystem scanned, not a frozen boot; AC4 (vector correctness) can run
  against either the frozen or unfrozen child with equal honesty, since
  model loading/inference code is identical either way — the frozen boot
  costs an extra ~75 s per verification run if it forces a rebuild, or is
  free if it reuses the `packaged` module-scoped fixture from
  `tests/test_desktop_package.py:271-283`. **Recommend reusing `packaged`**
  (same fixture, same bundle, avoids a second build) and launching
  `bundle/arxmcp-desktop-child` with the real launch/bound protocol,
  mirroring `_child_env()` but pointed at the frozen executable path.

## 6. Item 5 — Marker + gate wiring

- New marker `requires_bundled_model`, registered in `pyproject.toml`
  `[tool.pytest.ini_options].markers` (bumping "Eleven test markers" to
  twelve — `CLAUDE.md §4.5`'s count line and
  `tests/test_marker_doc_consistency.py`'s re-derivation both need the
  update; the derivation test will FAIL closed if the enumeration doc
  isn't touched, so this isn't optional).
- Add to `_OPT_IN_MARKERS` in `tests/conftest.py:120-133` — mandatory per
  issue #206's lesson (a marker registered but not added there silently
  runs on every `make test`, the exact bug this repo already paid for
  once).
- Follow `DESKTOP_PACKAGE_GATE`'s exact shape
  (`tests/conftest.py:52-56` `_DESKTOP_GATE_ENV` tuple + the
  `pytest_sessionfinish` any-skip-fails guard) — add a
  `DESKTOP_BUNDLED_MODEL_GATE` env var to that tuple so a drifted marker
  name can never silently degrade a `make desktop-model-check`-style
  target to zero-evidence green, mirroring m7's own H2/H5 lesson recorded
  in the Makefile comment at line ~150.
- New Makefile target (name suggestion: `desktop-model-check`, distinct
  from `desktop-package-check` since it's a separate, longer-running
  concern) sets `DESKTOP_BUNDLED_MODEL_GATE=1` and runs
  `pytest tests/test_desktop_bundled_model.py -m "requires_bundled_model or
  not requires_bundled_model"` — the same tautology-expression pattern
  already used twice (`desktop-conformance`, `desktop-package-check`).

**Runtime cost, stated honestly:** the milestone's own budget framing
(159 s / 358 s) is the m7 numbers; m8 adds on top. If AC4 reuses the
`packaged` fixture (§5's recommendation), the packaging build itself is
NOT paid twice — the marginal cost is: one BGE-M3 forward pass (~2-5 s
warm-cache CPU inference for a handful of golden strings) + one reranker
forward pass (~1-3 s for a handful of pairs) + process boot/readiness
poll (~15-30 s per `test_ac1_real_child_ready_and_console`'s own eager
warm-up precedent, `tests/test_desktop_child.py:319-327`) — call it
**+30-60 s** for `desktop-model-check` beyond whatever `desktop-package-check`
already paid, **assuming fixture reuse**; if the new gate provisions its
OWN separate build (not reusing `packaged`), add the full **~150 s** two-build
cost again. This is a genuine design decision with real cost implications
the implementer should make explicitly, not default into.

## 7. Item 6 — Honest LOC + file estimate

| Component | Est. LOC | Notes |
|---|---|---|
| `hook-faiss.py` or spec-level `Analysis().binaries` filter (§3) | 20-40 | Small, but needs the "don't drop the live copy" guard test |
| Single-file filesystem guard (§4a) | 30-60 | Reuses `scan_tree`/`file_manifest` machinery |
| Process-level BEFORE/AFTER regression (§4b) — new `arxmcp-desktop-omp-probe` EXE + entry script + spec wiring | 120-200 | Mirrors `probe_entry.py` (53 LOC) + spec additions (~20-30 LOC) + the fault-injection BEFORE arm (unproven design, budget generously: 60-100 LOC) |
| Golden fixture generation script (one-time, NOT part of test suite; may live under `.claude/` or `tools/`) | 60-100 | Encodes fixed strings through BGE-M3 + reranker, writes the fixture JSON |
| Golden fixture file itself | 0 LOC (data) | Small JSON, not counted |
| AC4 real-model gate test (`tests/test_desktop_bundled_model.py`, new file) | 150-250 | Boot (reused `packaged` fixture or new), encode, compare, path-containment assertion |
| Marker + conftest + Makefile + CLAUDE.md wiring (§5) | 20-40 | Mirrors m7's own delta exactly |
| **Total** | **~400-690** | |

**This is under the 800-LOC soft-abort threshold** (`plans/desktop-distribution-roadmap.md:248-259`
via `desktop-distribution-e4-blocker-research.md:592-598`'s citation), but
the range is WIDE — the §4b fault-injection BEFORE-arm design is
explicitly unproven (see §4b's own caveat) and could grow if the
`install_name_tool`-on-a-copy approach doesn't reliably reproduce the
crash and a different technique is needed. **Flag at implementation time
if §4b's BEFORE arm takes more than 2-3 iterations to get a genuine RED
result** — that is the single largest scope-growth risk in this
milestone, not the consolidation fix itself (§3) or the golden fixture
(§5), both of which are mechanically well-understood.

## 8. Per-AC provability notes; ACs that cannot be honestly satisfied as written

| AC (milestone brief numbering) | Provable / Assertable | Note |
|---|---|---|
| AC1 — exactly one `libomp.dylib` | **Provable.** Filesystem scan, deterministic, measured RED today (2 files), will be measured GREEN after §3's exclusion. | Straightforward. |
| AC2 — real FAISS+Torch collision test, RED before fix | **Cannot be honestly satisfied as literally written against the natural build.** See §2/§4b. The AFTER half (frozen bundle exits 0 post-fix) IS honestly provable. The BEFORE half (documented SIGABRT) requires an explicit fault-injection design that has NOT been empirically validated in this research pass — the implementer must prove out §4b's approach (or an alternative) before claiming this AC closed, and should not claim "reproduced the documented abort" without having actually observed a crash on the FROZEN artifact class, not just the unfrozen venv (which is already established and is not what this AC is asking to reproduce). |
| AC3 — `KMP_DUPLICATE_LIB_OK` absent, re-asserted under the new compute path | **Provable**, mechanically — reuse `FORBIDDEN_ENV`/`launch_environment` discipline (§4b). Trivial once §4b's launch harness exists. |
| AC4 — golden-vector real-model gate | **Provable**, but requires authoring the golden fixture from scratch (§5) — there is currently zero committed golden data anywhere in the repo for either BGE-M3 or the reranker. Budget this as new work, not "extend an existing fixture." |
| AC5 — no model file under the bundle | **Provable**, cheaply — `HF_HOME` already resolves outside any bundle path by construction (§5); the assertion is a straightforward inverted `validate_frozen_paths` walk of the bundle tree for `.bin`/`.safetensors`/`models--*` shaped paths, expected to pass trivially since nothing today writes models into `_internal/`. Low risk, low LOC. |
| AC6 — `make test` and `make desktop-conformance` exit 0 | **Provable**, mechanical gate re-run; the new marker's own gate target (`desktop-model-check` or equivalent) is a THIRD target this AC doesn't explicitly name — recommend the milestone's actual AC6 evidence also report that new target's result, even though the brief's text only names the two pre-existing ones. |

## 9. external_writes_required

- `git push origin main` (per-event authorization; no branch/MR per repo
  convention `CLAUDE.md §4.1/§4.4`).
- No GitLab/Confluence/AWS writes — this repo has no such surfaces in its
  external-write policy; the only external system this milestone touches
  is the local git remote.

## 10. Prior art / file:line index

- `.claude/notes/milestones/desktop-distribution-m7/implement/synthesis.md`,
  `.claude/notes/milestones/desktop-distribution-m7/rectify/summary.md` —
  what m7 shipped and its H1/H2/H3 fixes (config-dir isolation, frozen
  identity hashing, temp-root needle coverage).
- `.claude/notes/spikes/desktop-distribution-spike-1.md` — original OpenMP
  finding, now re-verified and narrowed (this build still shows the
  accidental single-copy resolution the ADR first found).
- `.claude/notes/spikes/desktop-distribution-e4-blocker-research.md` —
  blocker decomposition; §"Blocker 1" and "Blocker 2" are the direct
  ancestors of this milestone's ACs; my finding in §2 above is a material
  update to Blocker 1's "What must be true to call it closed" section (the
  process-level check's premise needs revision).
- `apps/desktop/pyinstaller/desktop_package.py:302-320` (`file_manifest`),
  `:369-432` (`scan_tree`) — reusable file-walk/hash machinery for §4a.
- `apps/desktop/pyinstaller/arxmcp_desktop.spec:44-107` — the
  `_sanitize_sysconfigdata` post-`Analysis()` mutation pattern to mirror
  for §3's exclusion.
- `apps/desktop/pyinstaller/probe_entry.py` (53 LOC) — the probe-EXE
  precedent for §4b's proposed third executable.
- `tests/test_desktop_package.py:52-64` (`_driver` dynamic import),
  `:271-283` (`packaged` module-scoped fixture), `:340-411` (exit-code
  discrimination via `_ENTERED_MAIN_MARKERS`/`_entered_main`) — patterns to
  reuse verbatim for §4b/§5's new tests.
- `tests/conftest.py:37-96` (KMP env handling), `:52-56`
  (`_DESKTOP_GATE_ENV`), `:120-167` (`_OPT_IN_MARKERS` +
  `pytest_collection_modifyitems`) — marker wiring precedent for §6.
- `tests/test_desktop_child.py:111-117` (`_child_env`), `:242-291`
  (`real_child` fixture), `:294-330` (`test_ac1_real_child_ready_and_console`
  asserting `warm == {"embedder": True, "lancedb": True, "reranker": True}`)
  — the boot-with-rerank precedent for §5.
- `tests/test_query_encoder.py:786-827` — the golden-vector GAP
  (`TestFrozenVectorContract`, empty) and the self-consistency-only
  `TestRealModelIntegration` that actually exists; both cited precisely in
  §5's correction.
- `tests/retrieval/test_rerank.py:734-780` — reranker's real-model test is
  latency-only, no correctness fixture; cited in §5.
- `server/model_loader.py:123-192` — `_huggingface_cache_root`
  (`$HF_HOME` precedence) and `assert_no_bin_in_snapshot` — reused for
  §5's "load-only isn't correctness" framing and the external-cache
  default.
- `server/cache.py:896-1085` — the Tier-2 FAISS cache
  (`_ensure_faiss_index`, `_tier2_lookup`, `_tier2_put`,
  `_rebuild_tier2_index`) — the REAL production code path that would
  naturally exercise FAISS add+search in-process with Torch inference,
  offered as an alternative compute trigger in §4b.
- `server/desktop_child.py` — entry point `main()`/`identity_source_path()`,
  confirmed unchanged by this research (no edits proposed).
- `tools/desktop_sidecar_spike.py:16` (`FORBIDDEN_ENV`), `:19-44`
  (`launch_environment`), `:93-99` (`validate_frozen_paths`) — reused
  verbatim in §4b and §5.
- `pyproject.toml:365-377` (markers block) — insertion point for the new
  `requires_bundled_model` marker.
- `CLAUDE.md §4.5` — "Eleven test markers" count line that must be bumped
  to twelve; `tests/test_marker_doc_consistency.py` enforces this.
