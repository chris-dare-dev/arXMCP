# Research Synthesis — textbook-md-heading-sectioning-m1

Single-mode milestone. Sole source: [research-brief-1.md](research-brief-1.md).
This synthesis records the load-bearing decisions; read the brief for full detail.

## The fix (locked)

In `ingest/textbook_renderer.py::_build_latex_wrapper`, add a **math-aware
heading-conversion pass BEFORE** the existing `_STRUCTURAL_CMD_RE` neutralization:

1. Line-by-line; match ATX headings with `^(#{1,6})\s+(.*?)\s*#*\s*$` (space after
   `#` run REQUIRED — FM-2; strips closed-ATX trailing `#` — FM-4).
2. Split the title on math spans `(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)`; escape
   `# % & _ { }` in the **non-math** segments ONLY (FM-1/FM-6 — escaping inside
   `$...$` corrupts math). Reassemble.
3. Depth → command: 1→`\section`, 2→`\subsection`, 3+→`\subsubsection`.
4. Non-heading lines pass through unchanged.
5. Existing structural-command neutralization runs on the converted body (order is
   load-bearing — FM-5: heading-first means a heading containing `\end{document}`
   still gets neutralized).

ATX only; setext (`===`/`---`) NOT handled (FM-3) — add a code comment. No new
dependency (stdlib `re` only; m6 synthesis ruled out markdown libs).

## Lockstep docstring correction (REQUIRED)

The `_build_latex_wrapper` docstring + module docstring currently claim prose-render
fidelity is irrelevant ("the retrieval substrate consumes math, not prose layout").
**That is wrong and is the root cause** — the e3 chunker's `_extract_section_chunks`
requires `ltx_section`/`ltx_chapter` divs (`_SECTION_DIV_CLASSES` in `ingest/chunker.py`),
so without heading→`\section` conversion the chunker emits ZERO chunks. Update the
docstring to state heading structure is required for the chunker to produce output.

## Tests (extend, don't replace)

Add methods to the EXISTING `TestBuildLatexWrapper` class in
`tests/test_textbook_renderer.py` (pure-Python, no LaTeXML): heading-level mapping,
math-in-title NOT escaped, special-char escaping in prose titles, closed-ATX trailing
`#` stripped, non-heading `#hashtag` (no space) NOT converted, math passthrough
preserved, structural-command neutralization still holds (do not regress
`test_plain_math_untouched_by_sanitizer`), no-headings input still yields a valid flat
doc. Optional bonus: a `requires_latexmlc`-gated assertion that `ltx_section` appears.

No tool-schema touch (`EXPECTED_TOOL_SCHEMA_SHA256` unchanged). No `KMP` concerns.

## Open questions
None.

## External writes required
None — purely local. Deliverables: `ingest/textbook_renderer.py` +
`tests/test_textbook_renderer.py`.
