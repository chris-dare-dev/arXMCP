# Research Synthesis — parser-fidelity-eval-m1

**Phase:** 1 (Research) → 2 (Implement)
**Mode:** single (1 Sonnet researcher)
**Brief merged:** `research-brief-1.md`
**Generated:** 2026-05-23

Single-mode dispatch — this synthesis promotes the one researcher's
brief as the authoritative implementation contract. The brief was
high-confidence end-to-end (Q1-Q3 resolved internally; 0 open
questions; 0 external writes). Orchestrator notes below capture the
key implementation pins and a final sequencing recommendation.

---

## Implementation contract (load-bearing decisions, pinned)

### D1. **NumPy + scipy only** for CDM impl

Avoid OpenCV (`cv2`) entirely — its Intel OpenMP runtime collides
with PyTorch's OpenMP under `faiss-cpu` on macOS per CLAUDE.md §8
gotcha 1 (`KMP_DUPLICATE_LIB_OK=TRUE` segfault landmine).

Researcher's key insight: **CDM bbox detection is color-keyed pixel
lookup, not connected-component analysis.** The CDM paper assigns
each LaTeX token a unique RGB color via `\mathcolor[RGB]{r,g,b}`
(5,832 distinct colors at interval-15 grid); after `pdflatex` +
`pdftoppm` rendering, each token's bbox is recoverable via
`np.where(image_array == target_color)` → extract min/max
row/col. **Pure NumPy suffices** for this; no edge detection, no
morphology, no scikit-image. scipy is needed ONLY for
`scipy.optimize.linear_sum_assignment` (BSD-3-Clause; Hungarian
assignment between predicted+ground-truth token sets).

**Action:** add `scipy>=1.10` to `pyproject.toml` deps. ~50 MB
install footprint. No OpenMP conflict.

### D2. Subprocess sandbox profile mirrors `parse_with_latexml` exactly

Per `tools/arxiv_fetch.py` precedent (E13_S03 hardening):

```python
proc = subprocess.Popen(
    [pdflatex_bin, "--no-shell-escape", "--interaction=nonstopmode",
     "-output-directory", str(tmpdir), str(tex_path)],
    cwd=tmpdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, start_new_session=True,
)
try:
    proc.communicate(timeout=30)
except subprocess.TimeoutExpired:
    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    raise
```

Same pattern for `pdftoppm` (poppler-utils). Both with 30s timeout
(vs LaTeXML's 300s — CDM renders single equations, not full papers).
On macOS: optional `sandbox-exec` profile (deprecated but functional
on Darwin 25.4.0 per E13_S03 audit). Document deprecation in
`.claude/docs/security-cdm-sandbox.md`.

### D3. `requires_pdflatex` marker mirrors `requires_latexmlc` style

From verbatim quote of pyproject.toml's existing entry:

> `requires_latexmlc: tests that invoke the real latexmlc binary
> (E10_S04 drift detector integration tests). Skipped by default;
> opt-in via pytest -m requires_latexmlc. Requires LaTeXML installed
> locally (brew install latexml / apt install latexml).`

New entry: `requires_pdflatex: tests that invoke the real pdflatex
+ pdftoppm binaries (parser-fidelity-eval-m1 CDM gate). Skipped by
default; opt-in via pytest -m requires_pdflatex. Requires pdflatex
(part of texlive: brew install --cask mactex-no-gui / apt install
texlive-base) and pdftoppm (part of poppler-utils: brew install
poppler / apt install poppler-utils) installed locally.`

Env-var opt-in: `ARXMCP_RUN_REAL_PDFLATEX=1` mirrors the existing
`ARXMCP_RUN_REAL_BGE_RERANKER=1` and similar patterns.

### D4. Commit ordering — **marker registration MUST precede tests**

If `requires_pdflatex` tests land before the marker is registered,
`pytest` emits an unknown-marker warning rather than skipping the
tests, polluting test output.

**Revised 5-commit sequence:**
1. (a) CDM impl + sandbox profile (`tools/cdm_eval.py` + sandbox
   doc `.claude/docs/security-cdm-sandbox.md`)
2. **(c-prime) Test marker registration in pyproject.toml**
   (must land BEFORE the tests that reference it — the brief's
   original (a)→(b)→(c) order would emit warnings)
3. (b) Fixture directory + 1-2 example pages
4. (Tests using the marker — embedded in commits a/b/c above; no
   separate test-commit)
5. (d) `.claude/TIER-GATES.md` amendment + README "Parser
   fidelity evaluation" subsection
6. (e) CLAUDE.md §4.5 amendment (documents `requires_pdflatex`)

Net 5 commits per the brief's target. Mostly the same as the brief
but commit (c) moves up to position 2 to avoid the warning.

### D5. CDM rendering uses `pdftoppm`, not ImageMagick

OmniDocBench reference impl uses ImageMagick (`convert`). arXMCP
should use `pdftoppm` (poppler-utils) — lighter, no ImageMagick
historical vulnerability surface (Image-Tragick CVE-2016-3714 etc.),
and already a common dep on math researchers' workstations (most
have texlive which suggests poppler too).

### D6. TIER-GATES.md gate is CONDITIONAL on fixture completion

Per researcher: the gate command (`pytest
tests/eval/test_parser_fidelity.py --cdm-min=0.85`) should
**cold-start skip** when the fixture directory has < 1 complete
page (mirrors the existing `test_retrieval_quality.py` cold-start
matrix). Promotion gate fires only when ≥ 1 page (development
unblock) or ≥ 20 pages (full promotion). Document both thresholds
in the gate row.

---

## Open questions (orchestrator-resolved)

All three Q1-Q3 in the brief were resolved by the researcher
internally. Orchestrator agrees with all three resolutions:
- Q1: use `pdftoppm`, skip on absent.
- Q2: implement `_wrap_formula_latex` helper with `xcolor` +
  `amsmath` preamble.
- Q3: use Milne AG notes (CC BY-NC) for the Milne-style sample
  page; attribute in fixture README.

**Net: zero open questions block implementation.**

---

## External writes the implementation will require

**Zero — purely local milestone.**

Researcher's brief: "No `git push`, no `gh issue create`, no infra
apply, no third-party API call." Confirmed by the implementation
scope: `tools/cdm_eval.py` + `tests/eval/` + `pyproject.toml` +
`TIER-GATES.md` + `README.md` + `CLAUDE.md` + `.claude/docs/` —
all under `$REPO_ROOT`.

Pre-push gate per CLAUDE.md §4.4 stays with user post-rect.

---

## Orchestrator synthesis note

The researcher's brief landed with NumPy-only as the decisive
recommendation — this answers the BRIEF's open question about
"OpenCV vs Pillow + scikit-image vs hand-rolled" by ruling out
both heavier options on first-principles grounds (CDM's algorithm
doesn't need connected-components; the KMP segfault landmine makes
OpenCV the wrong dep). This is the kind of opinionated synthesis
arXMCP's milestone-pipeline expects from single-mode dispatches.

Implementation can proceed INLINE (estimated ~400 LOC + ~20 tests,
under the INLINE-path threshold of 500 LOC / 5 files).
