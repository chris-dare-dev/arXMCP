# LaTeXML drift fixtures (E10_S04)

This directory is **dual-purpose**:

1. **Cron-job reference data.** `ops/cron/latexml-drift-check.sh`
   (daily) runs `python -m ops.drift_check`, which renders each
   `<name>.tex` through `latexmlc`, extracts the `<math>` elements,
   and diffs against the paired `<name>.expected.mathml`. Any drift
   causes ERROR logs + sentinel file + non-zero exit.
2. **Pytest fixtures.** The default test suite uses the same
   `.expected.mathml` files for mock-based unit tests of the diff
   logic; the integration test (marked `requires_latexmlc`) runs
   the real `latexmlc` end-to-end.

## Layout

| File pair | Coverage |
|---|---|
| `frac.{tex,expected.mathml}` | `\frac{a}{b}` — simplest fraction |
| `integral.{tex,expected.mathml}` | `\int_0^\infty f(x)\,dx` — `<msubsup>` form |
| `sum.{tex,expected.mathml}` | `\sum_{n=0}^{\infty} a_n` in `equation` env (locks the `<munderover>` display form) |
| `align.{tex,expected.mathml}` | Multi-line `\begin{align}` (multiple `<math>` per row) |
| `pmatrix.{tex,expected.mathml}` | `\begin{pmatrix}` matrix notation (multi-row, multi-column structure without tikz-cd) |

**`tikz-cd` is intentionally NOT a fixture at v1.** LaTeXML renders
`tikz-cd` as SVG with embedded `<math>` labels in `<foreignObject>`
elements; the extractor's `<math>` walk would pick up only the
label fragments, not the full diagram structure. Drift detection
on `tikz-cd` output would be unstable and high-noise.

## Regenerating baselines after a LaTeXML upgrade

```bash
python -m ops.drift_check --update-fixtures
```

This re-runs `latexmlc` on every `.tex` and overwrites the matching
`.expected.mathml`. Operator workflow: confirm the new LaTeXML
version is intentional, run the command, inspect the diff, then
commit. Analogous to `pytest --update-tool-schema-hash` for the
tool-schema hash.

## Why baselines diff `<math>` only, not raw HTML

`latexmlc`'s raw HTML output is NOT byte-stable across runs of the
same version — there's a timestamp in an HTML comment AND in a
visible `<div class="ltx_page_logo">`. `--nocomments` only
suppresses the XML comment, not the div. The drift detector
therefore parses the HTML via BeautifulSoup, extracts every
`<math>` element, and serializes them as a canonical string before
diff. The `<math>` content IS byte-stable across runs.

See `.claude/notes/milestones/E10_S04/research-synthesis.md` (D2)
for the design rationale.
