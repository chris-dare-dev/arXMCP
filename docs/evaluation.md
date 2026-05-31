# Evaluation gates

arXMCP has two quality gates: **retrieval quality** (does search return the
right chunks?) and **parser fidelity** (does PDF parsing preserve the math?).
Both are pytest-driven and skip cleanly when their fixtures or system
binaries are absent.

## Retrieval quality (nDCG@5 / Recall@10)

The Tier-0 → Tier-1 exit gate runs the retrieval harness against a curated
20-query fixture:

```sh
make eval        # pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.70
```

- A **SKIP is not a pass** for promotion — confirm the run reports
  `1 passed`, not `1 skipped`. The cold-start matrix skips when the fixture
  or corpus is missing.
- The full pass/fail/SKIP behavior and the operator prerequisite checklist
  are in [`.claude/TIER-GATES.md`](../.claude/TIER-GATES.md).
- Fixture hand-labeling is documented in
  [`.claude/docs/eval-curation.md`](../.claude/docs/eval-curation.md); the
  preliminary report is
  [`.claude/docs/retrieval-quality-report.md`](../.claude/docs/retrieval-quality-report.md).

## Parser fidelity (CDM)

The **CDM (Character Detection Matching)** gate at
[`tools/cdm_eval.py`](../tools/cdm_eval.py) measures how faithfully a PDF
parser preserves math-formula content (LaTeX → MathML → LaTeXML round-trip).
It is the prerequisite for any future PDF-parser bake-off.

It needs `pdflatex` + `pdftoppm` (not installed by default):

```sh
# macOS
brew install --cask mactex-no-gui && brew install poppler
# Debian/Ubuntu
sudo apt install texlive-base poppler-utils

# Run the gate (opt-in via env var + marker)
ARXMCP_RUN_REAL_PDFLATEX=1 \
  uv run python -m pytest tests/eval/test_parser_fidelity.py -m requires_pdflatex
```

### Interpreting CDM scores (F1 in [0, 1])

These bands are **arXMCP-chosen working defaults**, not upstream authority.
The 0.85 boundary is anchored on the Nougat-on-clean-papers ≈85% baseline;
the 0.70 / 0.95 boundaries are project judgment. Neither the CDM paper
(arXiv:2409.03643) nor OmniDocBench defines them. **Re-tune as bake-off data
accumulates** on the 20-page fixture.

| CDM score | Interpretation (arXMCP-chosen) |
|---|---|
| **≥ 0.95** | Near-perfect math fidelity — comparable to LaTeXML-on-source. |
| **0.85 – 0.95** | Acceptable for textbook ingest (Tier-1 promotion threshold). |
| **0.70 – 0.85** | Marginal; recommend a secondary parser (e.g. Mathpix-batch) on the worst pages. |
| **< 0.70** | Math-fidelity contract not met — parser rejected. |

The 0.85 threshold reflects the "math fidelity over coverage" stance from
[`.claude/notes/01-mission-and-context.md`](../.claude/notes/01-mission-and-context.md).
The 20-page eval fixture
([`tests/eval/textbook_fixtures/`](../tests/eval/textbook_fixtures/)) ships
with 2 example pages; operator-curated pages land incrementally per its
`README.md`.
