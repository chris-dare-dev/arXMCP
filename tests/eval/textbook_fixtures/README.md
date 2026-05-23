# Textbook fixture for CDM (Character Detection Matching) parser-fidelity eval

**Provenance:** parser-fidelity-eval-m1 (T2 spike from capability-scout
pdf-ingest-2026, CAND-14).

**Purpose:** ground-truth corpus for measuring math-formula extraction
fidelity (CDM F1) across the four textbook typesetting classes we
expect PDF parsers to encounter in arXMCP's textbook ingest path.

---

## Fixture layout

```
tests/eval/textbook_fixtures/
├── README.md                       # this file
├── paper-control/                  # 5 pages (clean math.AG arxiv paper)
│   ├── 01-formula.tex              # the formula's LaTeX source
│   ├── 01-formula.mathml           # ground-truth MathML (hand-typed v0)
│   ├── 02-formula.tex
│   ├── ...
├── hartshorne-style/               # 5 pages (single-column, dense math)
│   ├── 01-formula.tex
│   ├── ...
├── griffiths-harris-style/         # 5 pages (multi-column — adversary F-M3)
│   ├── ...
├── milne-style/                    # 5 pages (course-notes-as-PDF; clean .tex)
│   ├── ...
└── manifest.json                   # machine-readable index + provenance
```

**Per-page contract:**
- `NN-formula.tex` — a single math formula as a standalone LaTeX
  fragment (no preamble, no `\begin{document}` — just the body of
  `\[ ... \]`). 1-30 tokens typical; supports CDM grid capacity
  (4913 colors).
- `NN-formula.mathml` — the canonical MathML rendering of the same
  formula, used as ground truth. **The 2 v0 example pages under
  `paper-control/` use hand-typed sparse MathML** (≤ 50 lines, no
  `xref` / `<semantics>` / LaTeXML provenance attributes) —
  authored by the milestone operator as a working approximation,
  NOT regenerated via `latexmlc`. The operator MUST pick ONE
  ground-truth shape when adding the remaining 18 pages — either
  continue hand-typing (keep ≤ 50 lines, no LaTeXML markers) OR
  switch the entire fixture to LaTeXML-verbose form. Mixing the
  two shapes will distort CDM scoring because parser-emitted MathML
  matches one shape or the other but not both. See the regeneration
  section below.

---

## Agent-shipped scope (v0)

This commit ships:

1. The directory structure (4 subdirs, this README, `manifest.json`).
2. **2 example pages** under `paper-control/` with synthetic LaTeX
   that's expressive enough to exercise the CDM algorithm end-to-end
   (multi-token formulas with sub/super-scripts + commands).

The remaining **18 pages** are hand-curation work the **operator
completes separately**. Each page is ~1 hour of operator math
expertise (read the textbook page, identify a representative
formula, copy its LaTeX, hand-verify against a LaTeXML render or
write the MathML by hand). Total operator labor: ~20 hours, NOT
on the agent's critical path.

**This is intentional per the milestone brief.** The CDM eval gate
fires in `cold-start skip` mode when the fixture has fewer than 5
pages per class (TIER-GATES.md rule). Operator unblocks the gate
incrementally as fixture pages land.

---

## Cold-start behavior

The `tests/eval/test_parser_fidelity.py` harness inspects this
directory at test-collection time:

- **Fixture empty** (zero `.tex` files anywhere) → CDM tests skip
  with "fixture empty" message.
- **Fixture partial** (1-19 `.tex` files) → CDM tests run on what's
  present; aggregate score reported but **promotion gate does not
  fire** until ≥20 pages.
- **Fixture complete** (≥20 `.tex` files, spread across the 4
  classes) → promotion gate fires; parser must score mean CDM
  ≥ 0.85 to promote.

The cold-start matrix is documented in `.claude/TIER-GATES.md`.

---

## Attribution

`paper-control/` LaTeX sources are project-original synthetic
(no upstream attribution required).

When the operator adds `milne-style/` pages, source materials
should come from J.S. Milne's algebraic geometry notes
(`https://www.jmilne.org/math/CourseNotes/AG.pdf`, CC BY-NC
license). Each `milne-style/NN-formula.tex` must include a
comment header attributing the source page:

```latex
% Source: Milne, "Algebraic Geometry" v6.04 (2024-04-26),
%   p.42, Theorem 2.31. CC BY-NC.
```

`hartshorne-style/` and `griffiths-harris-style/` formulas should
be **operator-hand-typed** rather than copied from copyrighted
sources — the fixture purpose is to test the parser's handling of
the typesetting CLASS, not to redistribute textbook content. Keep
each formula short (≤50 tokens) and original.

---

## Regenerating

If `tools/cdm_eval.py` changes (e.g., interval-15 → interval-12 grid),
the fixture itself does not need regeneration — the `.tex` and
`.mathml` files are parser-independent ground truth.

**Switching ground-truth shape (hand-typed ↔ LaTeXML-verbose).** The
v0 example pages are hand-typed sparse MathML. If the operator
decides to commit the fixture to LaTeXML-verbose form (the
recommended path once the fixture exceeds ~5 pages — verbose form is
self-documenting and reproducible), run:

```bash
# CAUTION: re-bases every paper-control/milne-style page against
# LaTeXML's output. Tier-2 fixture-shape test will need its assertion
# flipped (≤ 50 lines vs contains <annotation encoding="application/
# x-tex">) — see tests/eval/test_parser_fidelity.py::TestFixtureShape.
for f in tests/eval/textbook_fixtures/{paper-control,milne-style}/[0-9][0-9]-formula.tex; do
  out="${f%.tex}.mathml"
  latexmlc --dest="$out" --noinvisibletimes "$f"
done
```

Then update `manifest.json::classes.paper-control.attribution` and
this README's per-page-contract paragraph to reflect the new shape,
and flip the shape assertion in
`tests/eval/test_parser_fidelity.py::TestFixtureShape`. Cross-check
the new MathML against the prior version via
`git diff --stat tests/eval/textbook_fixtures/` before committing.

The `hartshorne-style/` and `griffiths-harris-style/` classes
originate as PDF (no upstream `.tex`), so LaTeXML regeneration does
not apply — they remain hand-typed regardless of which shape the
LaTeXML-eligible classes use.

---

## Cross-references

- `tools/cdm_eval.py` — CDM impl
- `tests/eval/test_parser_fidelity.py` — pytest harness
- `.claude/TIER-GATES.md` — promotion gate definition
- `.claude/docs/security-cdm-sandbox.md` — subprocess sandbox doc
- `.claude/notes/milestones/parser-fidelity-eval-m1/` — milestone state
- `.claude/notes/capability-scouts/pdf-ingest-2026/artifacts/final-report.md` — RICE ranking + sequencing rationale
