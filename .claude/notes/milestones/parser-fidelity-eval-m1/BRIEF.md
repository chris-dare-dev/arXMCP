# Milestone Brief — parser-fidelity-eval-m1

**Provenance:** T2 spike from capability-scout `pdf-ingest-2026`.
Bundles CAND-7 (CDM gate) + CAND-14 (textbook eval fixture) from
`.claude/notes/capability-scouts/pdf-ingest-2026/artifacts/final-report.md`
into a single milestone. RICE-ranked #7 by formula but **#1 by
sequencing-priority** — keystone prerequisite for every PDF-parser
milestone per T2 ruling in `challenge.md`.

---

## Primary deliverables

### 1. CDM impl at `tools/cdm_eval.py`

**Reference:** arXiv:2409.03643 *"Image Over Text: Transforming
Formula Recognition Evaluation with Character Detection Matching"*
(Wang et al., CVPR 2025). Reference impl in `opendatalab/OmniDocBench`
(Apache-2.0) at `github.com/opendatalab/OmniDocBench` — **design-pattern
lift, not import** per CLAUDE.md §4.7 no-fork rule.

**Algorithm:**
1. Render predicted LaTeX → image via `pdflatex` + `pdftoppm`
   subprocess (mirrors the existing `latexmlc` subprocess pattern).
   Threat 3 sandbox profile required: hard timeout (30s should be
   sufficient), separate UID, filesystem write whitelist (TMPDIR
   only), no network.
2. Render ground-truth LaTeX → image via the same pipeline.
3. Detect characters in both renders via lightweight CV. **OpenCV
   is heavy** — verify M2 Max macOS install footprint vs
   `KMP_DUPLICATE_LIB_OK` landmine (CLAUDE.md §8 gotcha 1). If
   OpenCV adds another segfault path, prefer a lighter alternative
   (Pillow + scikit-image, or a hand-rolled bbox detector if equations
   have a constrained glyph alphabet).
4. Match characters via Hungarian assignment on bounding-box features.
5. Return CDM score in [0, 1].

**API:**
```python
def cdm_score(predicted_latex: str, ground_truth_latex: str) -> float:
    """Return CDM score in [0, 1]. 1.0 = perfect glyph match."""
```

Estimated ~hundreds of LOC + targeted tests.

### 2. 20-page hand-curated textbook fixture at `tests/eval/textbook_fixtures/`

**Composition:**
- 5 pages from a sample math.AG paper (control — clean typeset;
  competent parser should score near 1.0)
- 5 pages from Hartshorne-style typeset (single-column; the v1
  textbook target)
- 5 pages from Griffiths-Harris-style typeset (multi-column —
  adversary F-M3 concern)
- 5 pages from a Milne-style course-notes-as-PDF (rendered from
  `.tex` per author convention — friendliest case for parser fidelity)

**Per-page format:**
- Source PDF
- Ground-truth MathML (extracted via LaTeXML against original `.tex`
  if available; otherwise hand-typed by operator math expertise —
  ~1 hour per page = ~20 hours total of operator math labor)

**Agent scope (this milestone):** create the fixture DIRECTORY
STRUCTURE + 1-2 EXAMPLE PAGES with example ground-truth (synthetic
or borrowed-from-OmniDocBench-fixture with attribution). The
remaining 18 pages are hand-curation work the operator does
separately as a follow-up task.

### 3. Wire into `.claude/TIER-GATES.md` as Tier-1 promotion gate

> Path A parser must score mean CDM ≥ 0.85 on the textbook fixture
> before promotion.

Mirrors the existing nDCG@5 / Recall@10 retrieval-quality gates.

### 4. Document `requires_pdflatex` test marker in CLAUDE.md §4.5

Alongside the existing `requires_model` marker. Tests opt-in via
env var (default OFF in `make test`).

### 5. README addition: "Parser fidelity evaluation" subsection

Under Operations. Explains the CDM gate, how to run it, what
scores mean.

---

## T3 spike output (informational)

The T3 sample-of-10 spike at
`.claude/notes/capability-scouts/pdf-ingest-2026/spikes/source-availability.md`
returned **10-30% hit rate** (well below 60% threshold).

**Implication:** CAND-10 (source-first `.tex` fetcher) is NOT a
standalone milestone; it collapses into CAND-1's parser driver as a
~50-LOC fall-through helper.

**This is OUT OF SCOPE for parser-fidelity-eval-m1** — record as a
"see also" note in the implementation-summary for the future
parser-bake-off milestone.

---

## Hard constraints

- Per CLAUDE.md §4.7: `assert` is BANNED for invariants; pure-ASGI
  middleware only; no `anthropic` SDK at runtime in `server/`; no
  `claude-opus` references in `server/`.
- New test marker `requires_pdflatex` registered in `pyproject.toml`
  `[tool.pytest.ini_options]` markers list — mirror `requires_model`
  entry.
- `pdflatex` subprocess sandbox: hard timeout (30s should be
  sufficient for a single equation render); no network; filesystem
  write only to `TMPDIR`.
- OpenCV install footprint must be verified against the M2 Max segfault
  landmine.
- Single `state.json`; bundle CAND-7 + CAND-14 as one milestone.
- Test count delta target: +15 to +25 tests (CDM unit tests +
  fixture-validation tests + sandbox-discipline tests).
- 5 logical commits expected:
  (a) CDM impl + sandbox profile
  (b) fixture directory + 1-2 example pages
  (c) test marker registration + opt-in env var
  (d) TIER-GATES.md amendment + README addition
  (e) CLAUDE.md §4.5 amendment

## External writes expected

**Zero — purely local milestone.**
- No `git push`, no `gh issue create`, no infra apply, no
  third-party API call.
- Pre-push gate per CLAUDE.md §4.4 stays with user.
