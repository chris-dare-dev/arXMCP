"""Tests for the MinerU markdown → HTML5+MathML rendering bridge.

textbook-ingest-m6: Strategy A — wrap MinerU markdown as a LaTeX
document, run latexmlc once.

Three tiers (mirrors the textbook_parser test layout):

1. **Pure-Python unit tests** (always run). Cover helpers that don't
   invoke latexmlc: LaTeX envelope construction, flat-paper-id
   derivation. Plus a happy-path render with parse_with_latexml mocked.

2. **Integration tests** (gated behind ``requires_mineru`` +
   ``requires_latexmlc`` + their respective env vars). End-to-end via
   the real LaTeXML binary.
"""

from __future__ import annotations

import dataclasses
import os  # noqa: F401  (referenced by lazy skipif string-condition)
import shutil  # noqa: F401  (referenced by lazy skipif string-condition)
from pathlib import Path
from unittest.mock import patch

import pytest

from ingest import textbook_renderer
from ingest.textbook_parser import MinerUResult
from ingest.textbook_renderer import (
    RenderResult,
    _build_latex_wrapper,
    _flat_paper_id,
    render_mineru_to_html,
)

# ---------------------------------------------------------------------------
# Tier 1 — pure-Python unit tests
# ---------------------------------------------------------------------------


class TestBuildLatexWrapper:
    def test_envelope_present(self) -> None:
        out = _build_latex_wrapper("hello $x$ world")
        assert out.startswith("\\documentclass{article}")
        assert "\\usepackage{amsmath,amssymb}" in out
        assert "\\begin{document}" in out
        assert "\\end{document}" in out
        assert "hello $x$ world" in out

    def test_math_syntax_passes_through(self) -> None:
        body = "$$\\sum_{i=1}^n a_i$$"
        out = _build_latex_wrapper(body)
        assert body in out

    def test_empty_body(self) -> None:
        out = _build_latex_wrapper("")
        # Even empty body produces a valid skeleton; LaTeXML emits
        # an empty document.
        assert "\\documentclass" in out
        assert "\\end{document}" in out


class TestFlatPaperId:
    @pytest.mark.parametrize(
        "paper_id,expected",
        [
            ("textbook:my-book", "textbook_my-book"),
            ("hep-th/0001234", "hep-th_0001234"),
            ("2605.03890", "2605.03890"),
            ("textbook:nested/slug", "textbook_nested_slug"),
        ],
    )
    def test_flatten(self, paper_id: str, expected: str) -> None:
        assert _flat_paper_id(paper_id) == expected


class TestRenderResultIsFrozen:
    def test_cannot_reassign_field(self, tmp_path: Path) -> None:
        result = RenderResult(
            output_html_path=tmp_path / "index.html",
            wall_clock_s=1.0,
            latex_error_annotations=0,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.wall_clock_s = 999.0  # type: ignore[misc]


def _build_minimal_mineru_result(tmp_path: Path) -> MinerUResult:
    """Construct a MinerUResult pointing at a synthetic markdown + JSON.

    The renderer reads `markdown_path` and walks
    `output_dir/<stem>/auto/images` (optional). Returns a frozen
    MinerUResult with paths under tmp_path so the test owns cleanup.
    """
    output_dir = tmp_path / "mineru_out"
    pdf_stem = "test_book"
    auto = output_dir / pdf_stem / "auto"
    auto.mkdir(parents=True)
    markdown_path = auto / f"{pdf_stem}.md"
    markdown_path.write_text(
        "# Section 1\n\n"
        "An equation: $\\frac{a}{b}$ inline.\n\n"
        "$$\\sum_{i=1}^n a_i x^i$$\n",
        encoding="utf-8",
    )
    content_list_path = auto / f"{pdf_stem}_content_list.json"
    content_list_path.write_text("[]", encoding="utf-8")
    return MinerUResult(
        output_dir=output_dir,
        markdown_path=markdown_path,
        content_list_path=content_list_path,
        stdout="",
        stderr="",
        wall_clock_s=12.34,
    )


class TestRenderMineruToHtmlSurface:
    """Happy-path and error-path coverage with parse_with_latexml mocked."""

    def test_happy_path_returns_result(self, tmp_path: Path) -> None:
        mineru_result = _build_minimal_mineru_result(tmp_path)
        parsed_dir = tmp_path / "parsed"
        parsed_dir.mkdir()
        paper_id = "textbook:my-book"
        flat = "textbook_my-book"

        # Fake parse_with_latexml writes a stub index.html into
        # parsed_dir/<flat>/.
        def fake_parse(main_tex, parsed_dir, paper_id):  # noqa: ARG001
            out_dir = parsed_dir / paper_id
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "index.html").write_text(
                "<!DOCTYPE html><html><body>"
                "<math class=\"ltx_ERROR\">parse error</math>"
                "<math>good</math>"
                "</body></html>",
                encoding="utf-8",
            )
            return None

        with patch.object(
            textbook_renderer, "parse_with_latexml", side_effect=fake_parse,
        ) as mock:
            result = render_mineru_to_html(
                mineru_result, parsed_dir, paper_id,
            )

        assert isinstance(result, RenderResult)
        assert result.output_html_path == parsed_dir / flat / "index.html"
        assert result.output_html_path.is_file()
        assert result.wall_clock_s >= 0
        # The stub HTML has one <math class="ltx_ERROR"> annotation.
        assert result.latex_error_annotations == 1

        # parse_with_latexml was called with the FLATTENED paper_id
        # (so the on-disk path doesn't have colons).
        _, kwargs = mock.call_args
        assert kwargs["paper_id"] == flat
        assert kwargs["main_tex"].name == "main.tex"

    def test_writes_wrapped_latex_to_main_tex(
        self, tmp_path: Path,
    ) -> None:
        mineru_result = _build_minimal_mineru_result(tmp_path)
        parsed_dir = tmp_path / "parsed"
        parsed_dir.mkdir()
        paper_id = "textbook:my-book"

        captured: dict[str, str] = {}

        def fake_parse(main_tex, parsed_dir, paper_id):  # noqa: ARG001
            captured["tex_content"] = main_tex.read_text(encoding="utf-8")
            out_dir = parsed_dir / paper_id
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "index.html").write_text("<html></html>")
            return None

        with patch.object(
            textbook_renderer, "parse_with_latexml", side_effect=fake_parse,
        ):
            render_mineru_to_html(mineru_result, parsed_dir, paper_id)

        # The wrapper envelope is in the .tex file.
        tex = captured["tex_content"]
        assert "\\documentclass{article}" in tex
        assert "\\begin{document}" in tex
        # The MinerU markdown content is inside the envelope.
        assert "An equation: $\\frac{a}{b}$" in tex

    def test_missing_markdown_path_raises(self, tmp_path: Path) -> None:
        result = MinerUResult(
            output_dir=tmp_path,
            markdown_path=tmp_path / "nonexistent.md",
            content_list_path=tmp_path / "anything.json",
            stdout="", stderr="", wall_clock_s=0.0,
        )
        parsed_dir = tmp_path / "parsed"
        parsed_dir.mkdir()
        with pytest.raises(RuntimeError, match="MinerU markdown not at"):
            render_mineru_to_html(result, parsed_dir, "textbook:x")

    def test_latexml_silent_failure_raises(self, tmp_path: Path) -> None:
        """If latexmlc returns but no index.html is produced, render
        raises RuntimeError (FM-4 mitigation)."""
        mineru_result = _build_minimal_mineru_result(tmp_path)
        parsed_dir = tmp_path / "parsed"
        parsed_dir.mkdir()

        def fake_parse(main_tex, parsed_dir, paper_id):  # noqa: ARG001
            # Don't produce index.html.
            (parsed_dir / paper_id).mkdir(parents=True, exist_ok=True)
            return None

        with (
            patch.object(
                textbook_renderer, "parse_with_latexml",
                side_effect=fake_parse,
            ),
            pytest.raises(RuntimeError, match="no index.html"),
        ):
            render_mineru_to_html(
                mineru_result, parsed_dir, "textbook:my-book",
            )

    def test_images_copied_alongside_html(self, tmp_path: Path) -> None:
        mineru_result = _build_minimal_mineru_result(tmp_path)
        # Populate the MinerU images/ dir.
        pdf_stem = mineru_result.markdown_path.stem
        images_dir = mineru_result.output_dir / pdf_stem / "auto" / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        (images_dir / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        parsed_dir = tmp_path / "parsed"
        parsed_dir.mkdir()

        def fake_parse(main_tex, parsed_dir, paper_id):  # noqa: ARG001
            (parsed_dir / paper_id).mkdir(parents=True, exist_ok=True)
            (parsed_dir / paper_id / "index.html").write_text("<html></html>")
            return None

        with patch.object(
            textbook_renderer, "parse_with_latexml", side_effect=fake_parse,
        ):
            result = render_mineru_to_html(
                mineru_result, parsed_dir, "textbook:my-book",
            )

        # images/fig1.png copied alongside index.html.
        dest = result.output_html_path.parent / "images" / "fig1.png"
        assert dest.is_file()

    def test_no_images_dir_does_not_fail(self, tmp_path: Path) -> None:
        """If MinerU's images/ dir is absent, render still succeeds."""
        mineru_result = _build_minimal_mineru_result(tmp_path)
        parsed_dir = tmp_path / "parsed"
        parsed_dir.mkdir()

        def fake_parse(main_tex, parsed_dir, paper_id):  # noqa: ARG001
            (parsed_dir / paper_id).mkdir(parents=True, exist_ok=True)
            (parsed_dir / paper_id / "index.html").write_text("<html></html>")
            return None

        with patch.object(
            textbook_renderer, "parse_with_latexml", side_effect=fake_parse,
        ):
            result = render_mineru_to_html(
                mineru_result, parsed_dir, "textbook:my-book",
            )
        assert result.output_html_path.is_file()


# ---------------------------------------------------------------------------
# Tier 3 — Integration tests against the real LaTeXML binary
# ---------------------------------------------------------------------------


@pytest.mark.requires_latexmlc
@pytest.mark.skipif(
    "shutil.which('latexmlc') is None"
    " or os.environ.get('ARXMCP_RUN_REAL_LATEXMLC') != '1'",
    reason="latexmlc not on PATH, or ARXMCP_RUN_REAL_LATEXMLC != 1",
)
class TestRealLatexml:
    """End-to-end against the installed latexmlc binary.

    Not gated by ``requires_mineru`` because this tier exercises ONLY
    the renderer — it constructs a synthetic MinerUResult with a
    hand-crafted markdown file. Verifies the wrap-as-LaTeX +
    latexmlc invocation produces a valid HTML5+MathML document.
    """

    def test_synthetic_markdown_renders(self, tmp_path: Path) -> None:
        mineru_result = _build_minimal_mineru_result(tmp_path)
        parsed_dir = tmp_path / "parsed"
        parsed_dir.mkdir()
        result = render_mineru_to_html(
            mineru_result, parsed_dir, "textbook:my-book",
        )
        assert result.output_html_path.is_file()
        html_text = result.output_html_path.read_text(encoding="utf-8")
        assert "<math" in html_text  # MathML present
        # LaTeXML's HTML5 output emits <!DOCTYPE html>.
        assert html_text.lstrip().lower().startswith("<!doctype html>")
