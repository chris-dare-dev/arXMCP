# ADR-0007 — Math rendering is two-track: MathML Core + KaTeX (D7)

**Status:** Accepted (provisional; if the render spike fails, KaTeX
serves both tracks)
**Date:** 2026-07-04

## Context

Stage-1 finding 211 R-D/E-7/E-9 settled what the stored corpus actually
contains:

- **Stored ar5iv/LaTeXML paper HTML carries full presentation MathML**
  (`<math class="ltx_Math" alttext="…">` + `application/x-tex`
  annotations). Modern browsers (Chrome 109+, Firefox, Safari) render
  it natively via **MathML Core with zero JS** — ar5iv's MathJax loader
  is only an enhancement layer, blocked harmlessly by the preview CSP.
  (The old `ui.py` comment claiming "math displays as raw LaTeX" under
  `script-src 'none'` was wrong and has been corrected — erratum E-9.)
- **Chunk bodies store math as `$TeX$` text by design** (the chunker's
  F1 math-fidelity fix replaces `<math>` with verbatim `alttext`
  LaTeX), and MinerU-markdown textbook parses have no HTML at all.

No single renderer covers both.

## Decision

- **Stored-document surfaces** (paper preview, any reading pane over
  `ar5iv/`/`parsed/` HTML): **zero-JS native MathML Core**, pending the
  30-minute render-verification spike (open stored files under the
  existing `script-src 'none'` preview CSP in the target browser).
- **Chunk/retrieval surfaces** (search results, chunk detail, anything
  fed by `body_text`) and markdown-textbook content: **KaTeX**,
  self-hosted (reuse the same self-hosted font approach).
  Server-side KaTeX pre-render remains a future-enhancement candidate.

## Consequences

- The reading path stays JS-free and CSP-tight; only chunk-text
  surfaces pay the KaTeX bundle cost.
- The render spike is a WS-B M0-adjacent task; its failure flips track
  one to KaTeX without contract changes.
