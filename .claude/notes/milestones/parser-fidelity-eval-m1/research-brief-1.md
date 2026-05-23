# Research Brief — parser-fidelity-eval-m1

**Agent:** milestone-researcher (brief-1, single-mode)
**Generated:** 2026-05-23T05:30:00Z

---

## In-codebase context

### Design-constitution constraints that apply

**04-parsing-and-chunking.md — math-fidelity contract:**

> "Nougat hallucinated equation indices — Heuristic detection (equation count vs PDF page count); demote confidence"
> "Nougat ... Equation fidelity is acceptable on clean papers (~85%), much worse on dense hep-th preprints"

The CDM gate directly operationalizes the qualitative fidelity concern expressed here. The brief's ≥0.85 threshold on the textbook fixture is coherent with the parsing note's "acceptable on clean papers (~85%)" baseline for Nougat.

**08-security-observability-ops.md — Threat 3 sandbox profile (verbatim):**

> "LaTeXML runs in a subprocess with a hard timeout (5 minutes). Subprocess runs as a separate UID (Docker user namespace, or rootless container with an unprivileged user inside). Filesystem write whitelist (only the per-paper output directory). No network access from the LaTeXML subprocess. On macOS: `sandbox-exec` profile. On Linux: seccomp + landlock."
> "Never invoke LaTeXML inside the MCP server process itself."

`pdflatex` for CDM rendering is a peer threat to LaTeXML: same Turing-complete LaTeX, same `\write18` shell-escape risk, same file-system write concern. The existing E13_S03 work already implemented `sandbox-exec` (macOS) for LaTeXML in `tools/arxiv_fetch.py::parse_with_latexml` using `start_new_session=True` + `os.killpg`. The CDM subprocess must follow the same process-group-kill discipline. The 30s timeout in the brief (vs LaTeXML's 300s) is appropriate since CDM renders single equations, not full papers.

**tools/arxiv_fetch.py — subprocess discipline precedent (verbatim):**

> "proc = subprocess.Popen(cmd, cwd=main_tex.parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)"
> "os.killpg(os.getpgid(proc.pid), signal.SIGKILL)"

This is the exact pattern to mirror for `pdflatex` + `pdftoppm` subprocess chains in `tools/cdm_eval.py`. Wrap each subprocess call in `try/finally` with `os.killpg` on `TimeoutExpired`.

**CLAUDE.md §4.7 — banned patterns:**

- `assert` for invariants: BANNED. Use `if … raise RuntimeError(…)`.
- `BaseHTTPMiddleware`: BANNED (not relevant here — this milestone adds no middleware).
- `anthropic` SDK at runtime in `server/`, `ingest/`, `shim/`: BANNED. `tools/cdm_eval.py` lives in `tools/` — no server-path concern here.

**CLAUDE.md §8 — macOS segfault landmine (verbatim):**

> "macOS pytest segfault with `faiss-cpu` + PyTorch. The `KMP_DUPLICATE_LIB_OK=TRUE` workaround in `tests/conftest.py` is required for the full `pytest` run to not SIGSEGV."

OpenCV (`cv2`) imports Intel's MKL/OpenMP runtime, which conflicts with PyTorch's own OpenMP at the same path. This is the precise landmine. The brief correctly flags it. The recommendation below resolves it.

**TIER-GATES.md — existing gate format (verbatim):**

> "| Transition | Gate condition (command) | Owning milestone |"
> "| **Tier-0 → Tier-1** | `pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.70` passes … | E05_S02 |"

The new CDM gate must mirror this exactly: one command, machine-checkable exit code, owning milestone column entry. The command shape should be `pytest tests/eval/test_parser_fidelity.py --cdm-min=0.85`.

**pyproject.toml — existing marker registration (verbatim):**

```
"requires_latexmlc: tests that invoke the real `latexmlc` binary (E10_S04 drift detector integration tests). Skipped by default; opt-in via `pytest -m requires_latexmlc`. Requires LaTeXML installed locally (`brew install latexml` / `apt install latexml`)."
```

The `requires_pdflatex` marker must be registered in the same `[tool.pytest.ini_options] markers` list. The docstring format is verbatim from `requires_latexmlc` — the implementer should copy the style exactly.

**Current pyproject.toml — key absence:** `scipy` is NOT in the dependency list. NumPy is present (`numpy>=1.24`). `scipy.optimize.linear_sum_assignment` (BSD-3-Clause) must be added as a new dependency if used. Neither `opencv-python`/`cv2`, `scikit-image`, nor `Pillow` appear as direct deps. Pillow is a transitive dep (via `transformers` / `mcp`); scikit-image is not present at all.

**tests/eval/ — eval harness precedent:**

The existing eval harness uses `@pytest.mark.eval` registration, a cold-start skip matrix (skip vs fail distinction), atomic write via `os.replace`, and pytest custom flags (`--ndcg-min`, `--hybrid`, `--rerank`). The CDM gate test should follow the same shape: `@pytest.mark.eval` + `@pytest.mark.requires_pdflatex`, cold-start skip if `pdflatex` is absent or fixture directory is empty, threshold-failure via a `ThresholdNotMetError`-style exception, aggregate JSON written to `var/arxmcp/ops/eval/`.

---

## Prior decisions and lessons

**Recent git log analysis:**

Commits `25be357` → `afd57cc` span E13_S07c (CA pinning), verification-feedback-m3 (Lean REPL), E14_Tier5plus (bundled multi-milestone), and a capability-scout port. The E14_Tier5plus precedent (5-6 logical commits, bundled milestone) is the correct template for the 5-commit structure in the brief.

**E13_S03 — LaTeXML sandbox discipline (adjacent milestone):**

E13_S03 shipped Phase 1 of Threat-3 mitigation (process-group kill). The `security-threat-3-audit.md` referenced in `tools/arxiv_fetch.py` is at `.claude/docs/security-threat-3-audit.md`. The CDM sandbox doc should be named `.claude/docs/security-cdm-sandbox.md` or folded into the E13_S03 audit as a Phase 2 addendum — NOT placed in `docs/` (per doc-placement rule).

**E10_S04 — LaTeXML drift detector (closest precedent for parser-output-fidelity testing):**

E10_S04 shipped `requires_latexmlc` marker and integration tests that invoke the real `latexmlc` binary. The `requires_pdflatex` marker is a direct structural peer. The env-var opt-in pattern (`ARXMCP_RUN_REAL_BGE_RERANKER=1` → `ARXMCP_RUN_REAL_PDFLATEX=1`) is the precedent.

**E14_S04 — `make ops` cadence precedent:**

The brief does not mention `make ops`; the CDM gate is `make eval`-adjacent. No Makefile target needed beyond what `pytest` covers. The existing `make eval` (which calls `pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.70`) does NOT need modification — the CDM gate is a separate test file.

**Known landmine — E13_S03 noted `sandbox-exec` is deprecated on macOS but functional:**

From MEMORY: "macOS `sandbox-exec` is marked DEPRECATED (man page confirms). It is still functional on Darwin 25.4.0." This applies to the pdflatex sandbox too. Use `sandbox-exec` with a `.sb` profile for macOS; document deprecation.

**pdflatex security flags — from external research:**

`pdflatex --no-shell-escape` disables `\write18` shell escape entirely. This is the correct flag for CDM rendering of untrusted LaTeX (the CDM tool renders operator-provided or model-predicted LaTeX, not necessarily trusted source). Combine with: `--interaction=nonstopmode` (avoids hanging on errors), hard timeout + process-group kill (same as LaTeXML). The `\input` arbitrary-file-read risk is mitigated by sandboxing the working directory to TMPDIR (no access to `/etc/passwd` etc.) rather than by flags alone.

**BRIEF vs CODEBASE CONFLICT: no `requires_pdflatex` marker exists yet.**

The pyproject.toml has `requires_latexmlc` but NOT `requires_pdflatex`. The implementer must add it. This is not a conflict per se — the brief explicitly calls for it as a deliverable — but calling it out explicitly: the marker registration in pyproject.toml is a prerequisite for ALL CDM tests to work, so it must be commit (c) in the 5-commit sequence.

---

## External sources

### arXiv:2409.03643 — CDM algorithm (Wang et al., CVPR 2025)

The CDM algorithm has four stages per the HTML version (`arxiv.org/html/2409.03643v2`):

1. **Colored token rendering:** Each LaTeX token is assigned a unique RGB color from a list with fixed interval 15, range `(0,0,15)` to `(255,255,255)` = 5,832 distinct colors. The command `\mathcolor[RGB]{r,g,b}` is injected per token. Both predicted and ground-truth LaTeX are rendered this way via `pdflatex` → `pdftoppm`.
2. **Bbox detection via pixel color matching:** After rendering, pixels matching each assigned color identify the exact bounding box of each token. This does NOT require connected-component analysis or edge detection — it is pure color-keyed pixel lookup, which is implementable with NumPy alone (already a dep).
3. **Hungarian assignment:** Cost matrix `Lmatch = Wt×Lt + Wp×Lp + Wo×Lo` where Lt = token identity cost (0/0.05/1), Lp = L1 norm of normalized bbox coordinate differences, Lo = L1 norm of token ordering differences. `scipy.optimize.linear_sum_assignment` (BSD-3-Clause) handles the assignment.
4. **F1-Score:** `CDM = 2×TP / (2×TP+FP+FN)`. Optional `ExpRate@CDM = fraction of perfectly matched formulas (CDMi=1.0)`.

**Key implication:** The bbox detection step is color-keyed pixel lookup on rendered images, not connected-component detection. This means **OpenCV is NOT required** for the bbox detection step. NumPy suffices for pixel-color → bbox extraction. scipy is needed only for the Hungarian assignment.

### OmniDocBench reference impl (github.com/opendatalab/OmniDocBench, Apache-2.0)

The CDM lives in `metrics/cdm/`. System deps: Node.js, ImageMagick, pdflatex. Python requirements listed separately. The reference impl uses colored-token rendering (same as the paper). Design-pattern lift only per the no-fork rule. The key design pattern to lift: inject `\mathcolor` per token in a preprocessing step before `pdflatex` invocation.

### pdflatex sandboxing (from latexref.xyz, January 2025)

- `pdflatex --no-shell-escape` disables `\write18` entirely (even if enabled in `texmf.cnf`). This is the correct flag for CDM rendering.
- `pdflatex --interaction=nonstopmode` avoids hanging on error dialogs.
- The additional protection layer is filesystem isolation (TMPDIR-only writes) via macOS `sandbox-exec` or Linux seccomp. The subprocess-level flag is `--no-shell-escape`.
- Font decompression bombs in `.pfb`/`.pfm` files remain a theoretical risk — mitigated by the 30s timeout.

### scipy.optimize.linear_sum_assignment

BSD-3-Clause license (same tier as MIT; on arXMCP's allow-list). Available since scipy 0.17.0. Implementation is a Jonker-Volgenant algorithm (LAPJV), O(n³) worst case, O(n) typical for sparse cost matrices. **Not currently in pyproject.toml** — must be added. NumPy (already a dep) is scipy's only transitive dep that arXMCP doesn't already have; scipy itself adds ~50 MB to the install footprint but has no native library conflict risk.

### OpenCV vs Pillow + scikit-image vs NumPy-only

Given that the CDM algorithm's bbox detection is color-keyed pixel lookup (not connected-component analysis), **pure NumPy** suffices: `np.where(image_array == target_color)` → extract min/max row/col → that IS the bounding box. No OpenCV, no scikit-image, no Pillow required for bbox detection. Pillow is needed only for image loading (PDF→PNG conversion is done by `pdftoppm` → PNG files on disk; Pillow can load PNGs). Pillow is already a transitive dep. OpenCV is NOT needed and would introduce the `KMP_DUPLICATE_LIB_OK` segfault risk flagged in CLAUDE.md §8.

---

## Recommendation

**Implement `tools/cdm_eval.py` using NumPy + scipy only (no OpenCV, no scikit-image).**

Rationale: The CDM paper's colored-token pixel-tracking approach reduces bbox detection to `np.where(arr == color)`, which requires only NumPy (already present). The Hungarian assignment requires `scipy.optimize.linear_sum_assignment` (BSD-3-Clause; add to pyproject.toml). Pillow is already a transitive dep and can load PDFs rendered by `pdftoppm` as PNG. OpenCV would add the Intel OpenMP runtime that conflicts with PyTorch's OpenMP under `faiss-cpu` on macOS — the exact segfault landmine documented in CLAUDE.md §8 gotcha 1. The NumPy-only path is lighter (~50 MB for scipy vs ~50 MB for OpenCV), avoids all OpenMP conflicts, and the CDM algorithm does not require connected-component analysis because bbox detection is pure color lookup.

For the subprocess chain:
- Render: `pdflatex --no-shell-escape --interaction=nonstopmode <tex_file>` in TMPDIR, with `start_new_session=True` + `os.killpg` on `TimeoutExpired`, 30s timeout. Same discipline as `parse_with_latexml`.
- Convert: `pdftoppm -r 150 -png <pdf> <prefix>` to get PNG. `pdftoppm` is part of poppler-utils (available on macOS via `brew install poppler`; on Linux via `apt install poppler-utils`). This is lighter than ImageMagick (which the OmniDocBench reference uses) and avoids ImageMagick's historical vulnerability surface.

For the 5-commit sequence, commit the sandbox profile FIRST (commit a), then fixture structure (commit b), then marker registration (commit c) — marker must precede the tests that use it or `pytest` will warn about unknown markers, not skip them.

For the TIER-GATES.md amendment: add a new row with command `pytest tests/eval/test_parser_fidelity.py --cdm-min=0.85` and owning milestone `parser-fidelity-eval-m1`. The gate is CONDITIONAL — it fires only when the fixture directory is populated with at least 1 complete page (cold-start skip matrix identical to `test_retrieval_quality.py`). Document that promotion requires 20 pages, but 1 page suffices to unblock development.

This milestone does NOT modify `server/tools.py::ALL_TOOLS`. Tool schema re-pinning (`EXPECTED_TOOL_SCHEMA_SHA256`) is NOT required.

---

## Open questions

**Q1 — `pdftoppm` vs ImageMagick availability assumption:** The brief assumes `pdflatex` + `pdftoppm` as system deps. The existing `requires_latexmlc` marker pattern requires the binary to be on PATH and the test skips if absent. The `requires_pdflatex` marker should similarly skip (not fail) if `pdflatex` or `pdftoppm` is absent. The implementer must verify that `pdftoppm` (from poppler-utils) is the right choice over ImageMagick's `convert` — both work, but `pdftoppm` is lighter and avoids ImageMagick's security surface. **Resolved:** use `pdftoppm`; skip test if not on PATH.

**Q2 — `\mathcolor` macro availability in pdflatex:** The CDM algorithm requires injecting `\mathcolor[RGB]{r,g,b}` per token. This macro comes from the `xcolor` package (`\usepackage[x11names]{xcolor}`). The wrapped LaTeX must include this preamble injection. The implementer must verify that arXMCP's standard formula rendering produces a valid `\documentclass{article}` wrapper before calling `pdflatex`. **Resolved:** implement `_wrap_formula_latex(formula: str) -> str` that produces a standalone document with `xcolor` + `amsmath` + the colored-token injections.

**Q3 — 20-page fixture sourcing:** The brief scopes the agent to create the directory structure + 1-2 example pages. The "Milne-style course-notes-as-PDF" fixture requires identifying a specific freely-licensed source. The implementer should use J.S. Milne's freely-available algebraic geometry notes (jmilne.org/math; CC BY-NC) for the Milne-style sample, with attribution in the fixture's README. The operator completes the remaining 18 pages manually. **Resolved:** pick Milne AG notes as the Milne-style sample; document attribution; operator does the rest.

No open questions block implementation start. All three above are resolved within this brief.

---

## External writes the implementation will require

None — this milestone is purely local.

The brief explicitly states: "Zero — purely local milestone. No `git push`, no `gh issue create`, no infra apply, no third-party API call." This is confirmed by the implementation scope: `tools/cdm_eval.py` + `tests/eval/` additions + `TIER-GATES.md` + `pyproject.toml` + `CLAUDE.md` amendments. Pre-push gate per CLAUDE.md §4.4 stays with the user.
