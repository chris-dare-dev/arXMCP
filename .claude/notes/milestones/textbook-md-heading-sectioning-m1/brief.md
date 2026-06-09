# textbook-md-heading-sectioning-m1 — Convert MinerU markdown headings to LaTeX sectioning

## PROBLEM

The textbook-PDF ingest path (MinerU → LaTeXML → chunker) produces **ZERO chunks**
for every real MinerU-parsed PDF, making PDF-sourced papers unretrievable. Discovered
2026-06-08 while running the staged 9-PDF Phase-2 ingest for the
`bridgeland-stability-pdfs` notebook.

## ROOT CAUSE

`ingest/textbook_renderer.py::_build_latex_wrapper` wraps MinerU markdown verbatim
into a bare LaTeX `article` envelope
(`\documentclass{article}...\begin{document}{body}\end{document}`). MinerU emits
document structure as **markdown ATX headings** (`# title`, `## section`,
`### subsection`), which are NOT LaTeX sectioning commands. LaTeXML therefore renders
a FLAT document: the HTML has only `ltx_para`/`ltx_p`/`ltx_equation` classes and ZERO
`ltx_section`/`ltx_subsection`/`ltx_chapter`/`ltx_theorem` divs.

The textbook chunker (`ingest/textbook_chunker.py`) extracts:
- `_extract_section_chunks` — needs `ltx_section`/`ltx_chapter` (via
  `_SECTION_DIV_CLASSES` imported from `ingest/chunker.py`)
- `_extract_chunks_from_container` — needs theorem-like divs

With no structure, `chunk_textbook` returns `[]`. The shipped textbook-ingest e2e
(textbook-ingest-m1..m12) was evidently only validated against synthetic `ltx_section`
HTML fixtures, never a true MinerU-markdown→LaTeXML→chunk run, so this latent gap
shipped. Secondary symptom: raw markdown `#` chars reaching LaTeXML raise
`Error:misdefined:# The token T_PARAM[#] should never reach Stomach!`.

## PROVEN FIX (validated end-to-end 2026-06-08; NOT yet in the tree)

In `_build_latex_wrapper`, BEFORE wrapping, convert markdown ATX headings to LaTeX
sectioning:
- `# X`   → `\section{X}`
- `## X`  → `\subsection{X}`
- `### X` → `\subsubsection{X}`

Line-anchored, levels 1–3; deeper levels (`####+`) → `\subsubsection`. Escape
LaTeX-special chars in the converted heading TITLE text (`#`, `%`, `&`, `_` at minimum)
so stray chars do not raise `T_PARAM`. Keep math (`$...$`, `$$...$$`) passthrough and
the existing `_STRUCTURAL_CMD_RE` neutralization of
`\end{document}`/`\begin{document}`/`\documentclass` unchanged.

EVIDENCE: on paper `1611.02087` (already MinerU-parsed; markdown at
`var/arxmcp/notebooks/bridgeland-stability-pdfs/parsed/1611.02087/1611.02087/auto/1611.02087.md`,
26 headings), the converted `main.tex` run through `latexmlc` yields
`ltx_section:1 + ltx_subsection:25 + ltx_title:52`, and
`chunk_textbook('bridgeland-stability-pdfs','1611.02087')` then returns **21
section-grain chunks** (was 0).

## SCOPE / TASKS

- **(a)** Fix `ingest/textbook_renderer.py::_build_latex_wrapper` (heading conversion +
  title escaping). One function; keep the change minimal and the docstring accurate.
- **(b)** Add regression tests (`tests/test_textbook_renderer.py` or the existing
  renderer test module): heading-level mapping (`#`/`##`/`###` →
  section/subsection/subsubsection), special-char escaping in titles, math passthrough
  preserved, structural-command neutralization still holds, and a no-headings input
  still yields a valid (flat) document. Prefer asserting on the generated LaTeX string
  (fast, no LaTeXML needed); a `requires_latexmlc`-marked end-to-end assertion
  (`ltx_section` present) is optional/bonus.
- **(c)** `ruff` + full `make test` green (NOTE: ~29–66 pre-existing Windows-only
  failures per CLAUDE.md/memory; establish the baseline failure set BEFORE the change
  and prove zero NEW real failures).
- **(d)** Commit per repo conventions: conventional commits, co-author trailer, GPG
  will land UNSIGNED per the workstation's known no-secret-key state (see memory
  `gpg-signing-broken-on-workstation`) — do NOT use `--no-gpg-sign`, just let it land
  unsigned after the hook; never `--no-verify`.

## CONSTRAINTS / CONTEXT

- `ingest/textbook_renderer.py` feeds the security-audited MinerU/LaTeXML subprocess
  path; the wrapper output is later fed to `parse_with_latexml`. Keep the
  structural-command neutralization (m6 F3) intact — do not regress it.
- Windows-native dev. No make/console-scripts; tests run via
  `.venv/Scripts/python.exe -m pytest`. `latexmlc` at
  `C:/Strawberry/perl/site/bin/latexmlc.BAT` (PATH:
  `/c/Strawberry/perl/site/bin:/c/Strawberry/perl/bin:/c/Strawberry/c/bin`). MinerU bin
  at `C:/Users/cedar/venvs/mineru/Scripts/mineru.exe` (`ARXMCP_MINERU_BIN`) — only
  needed for full parse, NOT for the renderer unit tests.
- DOWNSTREAM GOAL (after this milestone completes, OUTSIDE its commit scope):
  re-render the already-MinerU-parsed PDFs from cached markdown (cheap, no re-parse)
  and run the remaining 8 MinerU parses + chunk/embed/write via
  `tools/notebook_textbook_ingest.py` to populate the `bridgeland-stability-pdfs`
  notebook (9 PDFs: 0912.0043, 1404.3143, 1611.02087, 1802.01134, 2201.03654,
  2506.21995, 2602.24016, hep-th/0403166, textbook:dc-lecture-notes). This milestone
  is ONLY the renderer fix + tests.
- A throwaway operator parse driver exists at `var/parse_pdfs.py` (gitignored) for the
  downstream ingest; it is NOT part of this milestone.
