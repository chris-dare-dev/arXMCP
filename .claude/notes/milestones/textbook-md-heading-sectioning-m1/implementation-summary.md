# Implementation Summary — textbook-md-heading-sectioning-m1

**One-line:** `_build_latex_wrapper` now converts markdown ATX headings to LaTeX
sectioning (math-aware escaping), so the textbook chunker emits chunks for real
MinerU PDFs instead of zero.

**Commit range:** `<feat-sha>` (single feat commit; filled at finalize).
**Path:** inline (orchestrator).

## What landed

`ingest/textbook_renderer.py`:
- New `_convert_markdown_headings_to_latex(markdown_content)` — line-anchored ATX
  detection (`^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$`), depth→`\section`/`\subsection`/
  `\subsubsection` (≥3 collapses), runs BEFORE structural-command neutralization.
- `_escape_heading_title` / `_escape_heading_prose` — math-aware: splits the title on
  `$...$`/`$$...$$` spans (`_MATH_SPAN_RE`) and escapes `\ # % & _ { }` in the PROSE
  segments only (FM-1). The leading `\` → `\textbackslash{}` makes a heading title
  containing `\end{document}` inert (FM-5), so a stray LaTeX command in heading prose
  cannot execute.
- `_build_latex_wrapper` calls the conversion first, then the existing
  `_STRUCTURAL_CMD_RE` neutralization (unchanged) on the converted body.
- Module docstring + `_build_latex_wrapper` docstring corrected — they previously
  (wrongly) claimed prose-render fidelity was irrelevant to the chunker; it is the
  root cause.

`tests/test_textbook_renderer.py`:
- 8 new methods in the existing `TestBuildLatexWrapper` class (pure-Python, no
  LaTeXML): level mapping, deep-collapse, inline-math-in-title NOT escaped,
  prose-special-char escaping, closed-ATX trailing-`#` stripped, `#hashtag` (no space)
  NOT a heading, heading-with-`\end{document}` made inert, no-headings flat doc
  unchanged.

## Acceptance criteria

- (a) `_build_latex_wrapper` fixed (heading conversion + math-aware escaping). ✅
- (b) Regression tests added (8, extend existing class). ✅
- (c) ruff clean on touched files; `TestBuildLatexWrapper` 15/15 pass. Full
  `test_textbook_renderer.py`: 27 passed, 1 skipped (`requires_latexmlc`), 1
  pre-existing Windows symlink-privilege failure
  (`test_symlink_in_images_not_dereferenced`, WinError 1314 — untouched code,
  known Windows class per CLAUDE.md §3). ✅ (zero NEW failures)
- (d) Commit per conventions (GPG unsigned per known no-key state; never
  `--no-verify`). ✅ at finalize.

## End-to-end proof (production code, real LaTeXML)

Re-rendered the cached `1611.02087` MinerU markdown through the now-fixed production
`render_mineru_to_html`: structural classes `ltx_section:1, ltx_subsection:25,
ltx_title:26`; `chunk_textbook(...)` → **21 chunks** (was 0).

## External writes
None — purely local.

## Deviations from the brief
- Brief listed escape set `# % & _` (+ `{ }` from research FM-6). Implementation ALSO
  escapes the leading `\` in heading prose → `\textbackslash{}` (research FM-5), which
  subsumes structural-command neutralization for heading titles. The downstream
  `_STRUCTURAL_CMD_RE` pass is retained unchanged for non-heading body lines. This is
  strictly safer than the brief's minimum and is covered by
  `test_heading_containing_structural_command_neutralized`.
