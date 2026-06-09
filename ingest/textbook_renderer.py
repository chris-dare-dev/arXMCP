"""MinerU markdown → HTML5+MathML rendering bridge (textbook-ingest-m6).

Implements **Strategy A** from research-synthesis §D1: wraps MinerU's
markdown output as a minimal LaTeX document and passes it through
``tools/arxiv_fetch.py::parse_with_latexml`` for the HTML5+MathML
conversion. The math syntax (``$...$`` / ``$$...$$``) survives the
wrap-as-LaTeX pass.

Markdown ATX headings (``# title`` / ``## section``) ARE converted to
LaTeX sectioning commands (``\\section`` / ``\\subsection`` / ...) before
wrapping — this is load-bearing, not cosmetic. The e3 chunker
(``ingest/textbook_chunker.py::_extract_section_chunks``) extracts chunks
from ``ltx_section`` / ``ltx_chapter`` divs (``_SECTION_DIV_CLASSES`` in
``ingest/chunker.py``); LaTeXML only emits those divs for real
``\\section`` commands, so without the conversion the chunker produces
ZERO chunks (textbook-md-heading-sectioning-m1). Other prose constructs
(``**emphasis**``, ``[links](urls)``, lists) still render as literal
characters — best-effort — because the chunker keys on section structure
and math blocks, not inline prose markup.

Why not Strategy B/C: researcher-2 verified ``latexmlmath`` has ~1s
per-call Perl startup overhead; running it per-equation for a math-
dense textbook serializes to hours. Strategy A reuses LaTeXML's
per-equation error recovery in a SINGLE subprocess invocation.

Cross-references
----------------
- ``ingest/textbook_parser.py::MinerUResult`` — the m5 contract this
  module consumes.
- ``tools/arxiv_fetch.py::parse_with_latexml`` — the LaTeXML subprocess
  helper this module delegates to (inherits process-group kill, sandbox
  profile, timeout discipline).
- ``.claude/docs/security-pdf-sandbox.md`` — the latexmlc invocation in
  the textbook path is a peer subprocess to the MinerU sandbox.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import shutil
import time
from pathlib import Path

from ingest.textbook_parser import MinerUResult
from tools.arxiv_fetch import _CONFIGURED_LATEXML_TIMEOUT_S, parse_with_latexml

logger = logging.getLogger(__name__)


#: Minimal LaTeX envelope wrapping MinerU's markdown. Loads amsmath +
#: amssymb so MinerU's math expressions (which commonly use ``\mathbb``,
#: ``\mathrm``, ``\sum``, etc.) parse cleanly through LaTeXML.
_LATEX_ENVELOPE = (
    "\\documentclass{article}\n"
    "\\usepackage{amsmath,amssymb}\n"
    "\\begin{document}\n"
    "{body}\n"
    "\\end{document}\n"
)


@dataclasses.dataclass(frozen=True)
class RenderResult:
    """Frozen result of a sandboxed MinerU-markdown → HTML5+MathML render.

    ``output_html_path`` is the on-disk path to the produced
    ``index.html``. ``latex_error_annotations`` counts the number of
    ``<math class="ltx_ERROR">`` tags in the output — LaTeXML's
    per-equation error-recovery markers; a non-zero count is a
    quality signal (the document parsed, but some equations were
    malformed and got the error annotation).
    """
    output_html_path: Path
    wall_clock_s: float
    latex_error_annotations: int


#: Structural LaTeX commands that, if present in the MinerU markdown
#: body, would corrupt the envelope: a bare ``\end{document}`` mid-
#: content terminates the document early and LaTeXML silently drops
#: everything after it (m6 F3 — content loss). ``\documentclass`` /
#: ``\begin{document}`` similarly confuse the single-document model.
#: A math/CS textbook that quotes LaTeX source or has verbatim
#: listings can plausibly contain these. We neutralize them by
#: inserting a zero-width-safe break in the command name so LaTeXML
#: renders them as literal text rather than acting on them.
_STRUCTURAL_CMD_RE = re.compile(
    r"\\(end|begin)\s*\{\s*document\s*\}|\\documentclass\b"
)


def _neutralize_structural_commands(markdown_content: str) -> int:
    """Count structural-command occurrences in RAW markdown (m6 F3).

    Quality/observability signal only — has no production caller. NOTE
    (F4): this counts occurrences in the raw markdown, whereas the actual
    neutralization in :func:`_build_latex_wrapper` runs on the
    HEADING-CONVERTED body. The two counts can diverge — e.g. a
    ``\\end{document}`` inside a markdown heading is rendered inert by the
    heading-prose escaping (leading ``\\`` → ``\\textbackslash{}``) before
    ``_STRUCTURAL_CMD_RE`` ever sees it, so the wrapper neutralizes 0 while
    this raw counter returns 1. Treat this as a coarse upper-bound metric,
    not the wrapper's exact neutralization count.
    """
    return len(_STRUCTURAL_CMD_RE.findall(markdown_content))


#: ``\begin{array}`` / ``\end{array}`` matcher (whitespace-tolerant) for the
#: math-balance sanitizer (textbook-render-robustness-m1).
_ARRAY_ENV_RE = re.compile(r"\\(begin|end)\s*\{\s*array\s*\}")


def _sanitize_math_balance(markdown_content: str) -> str:
    """Balance ``\\begin{array}`` / ``\\end{array}`` so a malformed MinerU
    export cannot abort the entire LaTeXML document.

    MinerU OCR sometimes drops ``\\begin{array}`` openers while keeping the
    ``\\end{array}`` closers (observed: 0 begins / 36 ends on arXiv
    ``1404.3143``). LaTeXML then raises ``\\@end@array Attempt to close
    boxing group`` and abandons the document body — the render collapses to a
    near-empty page and the chunker emits ZERO chunks. A degraded array beats
    a dropped document, so we make the array environments balanced:

    - Forward depth counter: ``\\begin{array}`` → depth+1, ``\\end{array}``
      → depth-1. An ``\\end{array}`` that would drive depth below zero is
      orphaned (no matching open) and is removed.
    - After the pass, any depth still open gets that many ``\\end{array}``
      appended so LaTeXML closes the arrays cleanly.

    Balanced arrays — including nested ones, and arrays inside ``$$...$$`` —
    net zero and are left byte-for-byte untouched, so well-formed math is
    never corrupted. Runs on RAW markdown (before heading conversion escapes
    backslashes). Scope is intentionally ``array`` only — the confirmed
    failure mode; ``$$`` parity is left alone (it was already balanced in the
    observed failure, and over-correcting display math risks real corruption).
    """
    depth = 0
    out_parts: list[str] = []
    last = 0
    for match in _ARRAY_ENV_RE.finditer(markdown_content):
        if match.group(1) == "begin":
            depth += 1
            continue
        # An \end{array} token.
        if depth == 0:
            # Orphaned closer: emit everything up to it, then skip the token.
            out_parts.append(markdown_content[last:match.start()])
            last = match.end()
        else:
            depth -= 1
    out_parts.append(markdown_content[last:])
    result = "".join(out_parts)
    if depth > 0:
        result += "\n\\end{array}" * depth
    return result


#: Markdown ATX heading matcher (textbook-md-heading-sectioning-m1).
#: Line-anchored; a space/tab after the ``#`` run is REQUIRED so a stray
#: ``#hashtag`` mid-prose is NOT a heading (research FM-2). Trailing
#: ``#`` (closed-ATX style, ``## Title ##``) is consumed and discarded
#: (research FM-4). Setext headings (``===`` / ``---`` underlines) are
#: NOT handled — MinerU emits ATX by default (research FM-3).
_ATX_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")

#: Heading depth → LaTeX sectioning command. ``article`` class has no
#: numbered level below ``\subsubsection``, so depth ≥ 3 collapses there.
_HEADING_LEVEL_CMD = {1: "section", 2: "subsection", 3: "subsubsection"}

#: Inline-math spans within a heading title. Escaping LaTeX-special chars
#: INSIDE ``$...$`` would corrupt the math (e.g. ``$x_i$`` → ``$x\_i$``),
#: so a title is split on these spans and only the PROSE segments are
#: escaped (research FM-1 — the highest-risk subtlety). Non-greedy and
#: newline-bounded so the regex cannot swallow the whole title on an
#: unbalanced ``$``. A lone/unbalanced ``$`` matches no span and therefore
#: lands in a PROSE segment, where ``_escape_heading_prose`` escapes it to
#: ``\$`` (F1) — without that escape a leaked raw ``$`` would open LaTeX
#: math mode and corrupt the rest of the title/body.
_MATH_SPAN_RE = re.compile(r"(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)")

#: LaTeX-special chars escaped in heading PROSE text (NOT inside the
#: title's math spans — those are split out first). ``#`` is the
#: load-bearing one — a raw ``#`` reaching LaTeXML raises
#: ``Error:misdefined:# The token T_PARAM[#]``; ``{`` / ``}`` must be
#: escaped so they cannot unbalance the ``\section{...}`` argument
#: (research FM-6). The leading ``\`` is escaped to ``\textbackslash{}``
#: so a stray LaTeX command in heading prose — including a literal
#: ``\end{document}`` — is rendered inert rather than executed (research
#: FM-5); a real math backslash (``$\mathbf{P}$``) is safe because the
#: math span is excluded from escaping.
_HEADING_PROSE_ESCAPE = {
    "\\": "\\textbackslash{}",
    "#": "\\#",
    "%": "\\%",
    "&": "\\&",
    "_": "\\_",
    "{": "\\{",
    "}": "\\}",
    # A lone/unbalanced ``$`` (no closing delimiter on the line) is not part
    # of a balanced math span — ``_MATH_SPAN_RE`` routes only NON-math
    # segments here — so escaping it to ``\$`` is safe and prevents it from
    # opening LaTeX math mode (F1). Balanced ``$...$`` spans are split out
    # before escaping and never reach this map.
    "$": "\\$",
}


def _escape_heading_prose(text: str) -> str:
    """Escape LaTeX-special chars in a non-math heading prose segment."""
    return "".join(_HEADING_PROSE_ESCAPE.get(ch, ch) for ch in text)


def _escape_heading_title(title: str) -> str:
    """Escape a heading title, leaving inline math spans untouched.

    Splits ``title`` on ``$...$`` / ``$$...$$`` spans and escapes only the
    prose segments (research FM-1). ``re.split`` with a single capturing
    group yields prose at even indices and the math spans (verbatim) at
    odd indices.
    """
    parts = _MATH_SPAN_RE.split(title)
    return "".join(
        part if i % 2 else _escape_heading_prose(part)
        for i, part in enumerate(parts)
    )


def _convert_markdown_headings_to_latex(markdown_content: str) -> str:
    """Convert markdown ATX headings to LaTeX sectioning commands.

    ``# X`` → ``\\section{X}``, ``## X`` → ``\\subsection{X}``,
    ``### X`` (and deeper) → ``\\subsubsection{X}``. Non-heading lines pass
    through unchanged. Heading titles are escaped math-awarely via
    :func:`_escape_heading_title`.

    Runs BEFORE the structural-command neutralization in
    :func:`_build_latex_wrapper`. A heading title is made fully inert by
    prose escaping (the leading ``\\`` becomes ``\\textbackslash{}``), so a
    title containing a literal ``\\end{document}`` cannot terminate the
    document early (research FM-5); the downstream structural pass still
    guards NON-heading body lines, which are not escaped here.
    """
    out_lines: list[str] = []
    for line in markdown_content.split("\n"):
        match = _ATX_HEADING_RE.match(line)
        if match is None:
            out_lines.append(line)
            continue
        depth = len(match.group(1))
        cmd = _HEADING_LEVEL_CMD.get(depth, "subsubsection")
        title = _escape_heading_title(match.group(2).strip())
        out_lines.append(f"\\{cmd}{{{title}}}")
    return "\n".join(out_lines)


def _build_latex_wrapper(markdown_content: str) -> str:
    """Wrap MinerU markdown as a minimal LaTeX document.

    Markdown ATX headings (``# title`` / ``## section``) are converted to
    LaTeX sectioning (``\\section`` / ``\\subsection`` / ``\\subsubsection``)
    so LaTeXML emits the ``ltx_section`` divs the e3 chunker requires —
    without this the chunker produces zero chunks
    (textbook-md-heading-sectioning-m1). Math syntax (``$...$``,
    ``$$...$$``) passes through unchanged, including inside heading titles
    (escaping is math-aware).

    m6 F3: structural commands (``\\end{document}``,
    ``\\begin{document}``, ``\\documentclass``) in the body are
    neutralized by escaping the leading backslash so LaTeXML renders
    them as literal text rather than acting on them — otherwise a
    bare ``\\end{document}`` mid-content would silently truncate the
    rendered document. The math-bearing ``$...$`` content is
    untouched (the regex matches only the three document-structure
    commands).
    """
    # 0. Balance \begin{array}/\end{array} so a malformed MinerU export does
    #    not abort the LaTeXML document (textbook-render-robustness-m1). Runs
    #    on RAW markdown, before heading conversion escapes backslashes.
    balanced = _sanitize_math_balance(markdown_content)
    # 1. Convert markdown ATX headings to LaTeX sectioning FIRST. This is
    #    the load-bearing fix: the e3 chunker keys on ltx_section divs,
    #    which LaTeXML only emits for real \section commands.
    sectioned = _convert_markdown_headings_to_latex(balanced)
    # 2. Escape the leading backslash of any structural command so it
    #    becomes literal text (``\textbackslash end{document}``-style is
    #    overkill; ``\\end{document}`` → ``\end {document}`` would still
    #    match \end, so insert a brace-group guard instead: replace the
    #    backslash with ``\textbackslash{}`` which LaTeXML renders as a
    #    literal backslash followed by the (now-inert) command name).
    #    Runs AFTER heading conversion (research FM-5) so a heading whose
    #    title contains \end{document} is still neutralized.
    safe_body = _STRUCTURAL_CMD_RE.sub(
        lambda m: "\\textbackslash{}" + m.group(0)[1:],
        sectioned,
    )
    return _LATEX_ENVELOPE.replace("{body}", safe_body)


def _flat_paper_id(paper_id: str) -> str:
    """Mirror the on-disk-path flattening used by the upload handler.

    See ``server/routes/notebooks.py:882`` — ``textbook:my-book`` →
    ``textbook_my-book`` (colon flattened to underscore). Slashes
    (arXiv-style) are also flattened.
    """
    return paper_id.replace("/", "_").replace(":", "_")


def render_mineru_to_html(
    result: MinerUResult,
    parsed_dir: Path,
    paper_id: str,
) -> RenderResult:
    """Render a MinerU output bundle to HTML5+MathML on disk.

    Parameters
    ----------
    result
        The :class:`MinerUResult` from a sandboxed MinerU invocation
        (m5 driver). ``result.markdown_path`` is read here; the rest
        of the output_dir is left untouched (operator may inspect
        debug PDFs / JSONs separately).
    parsed_dir
        Per-notebook parsed root (typically
        ``var/arxmcp/notebooks/<slug>/parsed/``). The function creates
        ``parsed_dir/<flat_paper_id>/`` and writes ``index.html`` there.
    paper_id
        Full paper_id form (e.g. ``"textbook:my-book"``). Internally
        flattened to a path-safe form via :func:`_flat_paper_id`.

    Returns
    -------
    RenderResult
        Frozen dataclass naming the output html path, wall-clock
        elapsed, and the count of LaTeXML per-equation error
        annotations in the output (quality metric for m6 + downstream
        CDM eval).

    Raises
    ------
    RuntimeError
        - If ``result.markdown_path`` is unreadable.
        - If ``parse_with_latexml`` completed but no ``index.html`` was
          produced (FM-4 catches output-tree drift from the LaTeXML
          side).
    """
    if not result.markdown_path.is_file():
        raise RuntimeError(
            f"MinerU markdown not at {result.markdown_path!s}; "
            f"m5 driver should have produced it."
        )

    started = time.monotonic()
    flat = _flat_paper_id(paper_id)
    work_dir = parsed_dir / flat
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1. Read MinerU markdown.
    markdown_content = result.markdown_path.read_text(encoding="utf-8")

    # 2. Wrap as LaTeX. Write to a .tex file in the work dir so
    #    parse_with_latexml's cwd-set-to-source-dir convention works.
    tex_content = _build_latex_wrapper(markdown_content)
    main_tex = work_dir / "main.tex"
    main_tex.write_text(tex_content, encoding="utf-8")

    # 3. Run latexmlc via the existing sandboxed helper. Note that
    #    parse_with_latexml writes to parsed_dir/<paper_id>/index.html
    #    — but we want parsed_dir/<flat_paper_id>/index.html. Pass
    #    flat as the paper_id arg so the function's subdirectory
    #    convention aligns with our layout. The timeout is the
    #    env-configurable _CONFIGURED_LATEXML_TIMEOUT_S (default 300s) so
    #    math-dense papers can render past the old hardcoded 300s cap
    #    (textbook-render-robustness-m1); the helper's killpg/sandbox
    #    discipline is unchanged.
    parse_with_latexml(
        main_tex=main_tex,
        parsed_dir=parsed_dir,
        paper_id=flat,
        timeout=_CONFIGURED_LATEXML_TIMEOUT_S,
    )

    # 4. Copy MinerU's images/ dir alongside index.html so relative
    #    <img src="images/..."> references in the produced HTML
    #    resolve. The m5 driver leaves them under
    #    output_dir/<pdf_stem>/auto/images/.
    pdf_stem = result.markdown_path.stem
    mineru_images = result.output_dir / pdf_stem / "auto" / "images"
    if mineru_images.is_dir() and any(mineru_images.iterdir()):
        dest_images = work_dir / "images"
        if dest_images.exists():
            shutil.rmtree(dest_images)
        # m6 F5: symlinks=True PRESERVES symlinks rather than
        # dereferencing them. MinerU's output dir is attacker-
        # influenced (it ran on an uploaded PDF); a symlink planted
        # under images/ (e.g. images/x -> /etc/passwd) must NOT have
        # its target content copied into the notebook tree. Preserved
        # (dangling) symlinks are harmless — nothing downstream
        # follows them, and the notebook-scoped layout bounds the
        # blast radius.
        shutil.copytree(mineru_images, dest_images, symlinks=True)

    # 5. Verify the output landed where expected.
    index_html = work_dir / "index.html"
    if not index_html.is_file():
        listing = sorted(p.name for p in work_dir.iterdir())
        raise RuntimeError(
            f"latexmlc completed but no index.html at {index_html!s}. "
            f"work_dir contents: {listing!r}. Output-tree convention "
            f"may have changed (FM-4)."
        )

    # 6. Count LaTeXML error annotations — quality signal for the
    #    operator + downstream CDM eval.
    #    m6 F6: match the ltx_ERROR class as a token within a
    #    (possibly multi-class, possibly single-quoted) class
    #    attribute. LaTeXML emits e.g. class="ltx_ERROR ltx_font_bold"
    #    and can apply the class to <span> as well as <math>; an
    #    exact `class="ltx_ERROR"` match would silently read 0 on
    #    those variants and hide math degradation.
    html_text = index_html.read_text(encoding="utf-8")
    error_count = len(
        re.findall(r"""class=["'][^"']*\bltx_ERROR\b[^"']*["']""", html_text)
    )
    if error_count > 0:
        logger.warning(
            "textbook_renderer: %d <math class=\"ltx_ERROR\"> annotations "
            "in %s (per-equation parse errors recovered by LaTeXML)",
            error_count, index_html,
        )

    wall_clock_s = time.monotonic() - started
    logger.info(
        "textbook_renderer: rendered %s in %.2fs (errors=%d)",
        index_html.relative_to(parsed_dir), wall_clock_s, error_count,
    )

    return RenderResult(
        output_html_path=index_html,
        wall_clock_s=wall_clock_s,
        latex_error_annotations=error_count,
    )
