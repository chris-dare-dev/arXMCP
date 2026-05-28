"""MinerU markdown → HTML5+MathML rendering bridge (textbook-ingest-m6).

Implements **Strategy A** from research-synthesis §D1: wraps MinerU's
markdown output as a minimal LaTeX document and passes it through
``tools/arxiv_fetch.py::parse_with_latexml`` for the HTML5+MathML
conversion. The math syntax (``$...$`` / ``$$...$$``) survives the
wrap-as-LaTeX pass; markdown prose constructs (``## headers``,
``**emphasis**``, ``[links](urls)``, lists) render as literal
characters in the HTML output — best-effort. The chunker (e3)
consumes math blocks regardless of prose-render fidelity.

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
from tools.arxiv_fetch import parse_with_latexml

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


def _build_latex_wrapper(markdown_content: str) -> str:
    """Wrap MinerU markdown as a minimal LaTeX document.

    Math syntax (``$...$``, ``$$...$$``) passes through unchanged.
    Prose constructs render as literal text in LaTeX — acceptable
    for v1 (the retrieval substrate consumes math, not prose layout).
    """
    return _LATEX_ENVELOPE.replace("{body}", markdown_content)


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
    #    convention aligns with our layout.
    parse_with_latexml(
        main_tex=main_tex,
        parsed_dir=parsed_dir,
        paper_id=flat,
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
        shutil.copytree(mineru_images, dest_images)

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
    html_text = index_html.read_text(encoding="utf-8")
    error_count = len(re.findall(r'class="ltx_ERROR"', html_text))
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
