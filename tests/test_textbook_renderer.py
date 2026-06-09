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

    def test_structural_command_in_body_neutralized(self) -> None:
        """m6 F3: a bare \\end{document} in the body must NOT terminate
        the envelope early; content after it must survive."""
        body = "before $x$\n\\end{document}\nAFTER $y$"
        out = _build_latex_wrapper(body)
        # The AFTER content survives into the wrapped document.
        assert "AFTER $y$" in out
        # There is exactly ONE real \end{document} — the envelope's
        # closing one. The body's structural command was neutralized
        # (its backslash replaced with \textbackslash{}).
        # Count actual \end{document} occurrences NOT preceded by the
        # textbackslash neutralization marker.
        assert out.rstrip().endswith("\\end{document}")
        assert "\\textbackslash{}end{document}" in out

    def test_begin_document_in_body_neutralized(self) -> None:
        body = "x $a$\n\\begin{document}\ny $b$"
        out = _build_latex_wrapper(body)
        assert "y $b$" in out
        assert "\\textbackslash{}begin{document}" in out

    def test_documentclass_in_body_neutralized(self) -> None:
        body = "intro\n\\documentclass{book}\noutro"
        out = _build_latex_wrapper(body)
        assert "outro" in out
        assert "\\textbackslash{}documentclass" in out

    def test_plain_math_untouched_by_sanitizer(self) -> None:
        """The structural-command sanitizer must NOT touch ordinary
        math / prose — only the three document-structure commands."""
        body = "$\\frac{a}{b}$ and \\sum and \\begin{align}x\\end{align}"
        out = _build_latex_wrapper(body)
        # \begin{align} / \end{align} are NOT document-structure
        # commands — they pass through unchanged.
        assert "\\begin{align}" in out
        assert "\\end{align}" in out
        assert "\\textbackslash{}" not in out

    # -- textbook-md-heading-sectioning-m1: ATX heading → LaTeX sectioning --

    def test_atx_heading_levels_mapped(self) -> None:
        """# / ## / ### map to section / subsection / subsubsection so
        LaTeXML emits the ltx_section divs the e3 chunker requires."""
        body = "# Title\n\n## Section one\n\n### Sub A\n\nprose $x$ here"
        out = _build_latex_wrapper(body)
        assert "\\section{Title}" in out
        assert "\\subsection{Section one}" in out
        assert "\\subsubsection{Sub A}" in out
        # Non-heading prose is preserved verbatim.
        assert "prose $x$ here" in out
        # The raw ATX markers are gone (converted, not left as literals).
        assert "\n# Title" not in out
        assert "## Section one" not in out

    def test_deep_heading_collapses_to_subsubsection(self) -> None:
        """#### and deeper collapse to subsubsection (article has no
        deeper numbered level)."""
        out = _build_latex_wrapper("#### Deep\n##### Deeper\n###### Deepest")
        assert out.count("\\subsubsection{") == 3
        assert "\\subsubsection{Deep}" in out
        assert "\\subsubsection{Deepest}" in out

    def test_inline_math_in_heading_not_escaped(self) -> None:
        """FM-1: special chars INSIDE a heading's $...$ span must NOT be
        escaped — escaping ``$x_i$`` to ``$x\\_i$`` corrupts the math."""
        out = _build_latex_wrapper("## The space $\\mathbf{P}^2$ and $x_i$")
        # Math spans survive byte-for-byte.
        assert "$\\mathbf{P}^2$" in out
        assert "$x_i$" in out
        # The underscore inside math is NOT escaped.
        assert "x\\_i" not in out
        # And it is wrapped as a subsection.
        assert "\\subsection{" in out

    def test_prose_special_chars_in_heading_escaped(self) -> None:
        """FM-1/FM-6: special chars in heading PROSE text are escaped so a
        stray # cannot raise LaTeXML T_PARAM and {/} cannot unbalance the
        \\section{} argument."""
        out = _build_latex_wrapper("## Cohomology & C# of {X}_n 50% done")
        assert "\\subsection{" in out
        assert "\\&" in out
        assert "\\#" in out
        assert "\\{X\\}" in out
        assert "\\_n" in out
        assert "\\%" in out

    def test_closed_atx_trailing_hashes_stripped(self) -> None:
        """FM-4: closed-ATX trailing #'s are not part of the title."""
        out = _build_latex_wrapper("### The proof ###")
        assert "\\subsubsection{The proof}" in out
        # The trailing hashes did not leak into the title (escaped or raw).
        assert "The proof \\#" not in out
        assert "The proof ###" not in out

    def test_hash_without_space_is_not_a_heading(self) -> None:
        """FM-2: ``#hashtag`` (no space after the # run) is not a heading
        and must pass through as a literal line, not become a section."""
        out = _build_latex_wrapper("#hashtag not a heading\n\n## real")
        assert "\\section{hashtag" not in out
        assert "#hashtag not a heading" in out
        assert "\\subsection{real}" in out

    def test_heading_containing_structural_command_neutralized(self) -> None:
        """FM-5: a heading whose title literally contains \\end{document}
        is converted to a section AND made inert — prose escaping turns the
        leading backslash into \\textbackslash{} so it cannot terminate the
        document early."""
        out = _build_latex_wrapper("# Intro to \\end{document} usage")
        # Wrapped as a section…
        assert "\\section{" in out
        assert "Intro to" in out and "usage" in out
        # …the title's backslash is neutralized (rendered inert)…
        assert "\\textbackslash{}end" in out
        # …and the only real, command-active \end{document} is the
        # envelope's closing one (document not truncated early).
        assert out.rstrip().endswith("\\end{document}")
        assert out.count("\\end{document}") == 1

    def test_no_headings_yields_flat_document_unchanged(self) -> None:
        """A body with no headings is wrapped verbatim — the conversion
        pass is a no-op and introduces no \\section / escaping."""
        body = "just prose with $a+b$ and a list:\n- one\n- two"
        out = _build_latex_wrapper(body)
        assert body in out
        assert "\\section" not in out
        assert "\\textbackslash{}" not in out

    def test_unbalanced_dollar_in_heading_escaped(self) -> None:
        """F1: a lone/unbalanced $ in a heading title must be escaped to
        \\$ — a raw $ would open LaTeX math mode and corrupt the title and
        everything downstream until the next $."""
        out = _build_latex_wrapper("## Price is $5 today")
        assert "\\subsection{Price is \\$5 today}" in out
        # No raw lone $ leaked into the section argument.
        assert "{Price is $5" not in out

    def test_unbalanced_dollar_then_special_char_escaped(self) -> None:
        """F2: trailing prose after an unbalanced $ is escaped, and the $
        itself is escaped (no broken math context)."""
        out = _build_latex_wrapper("## no closing $x_i here")
        assert "\\subsection{no closing \\$x\\_i here}" in out
        # The $ is escaped (\$), so it cannot flip into math mode: there is
        # no bare $ (one not immediately preceded by a backslash) in the body.
        assert "\\$x" in out

    def test_math_only_heading_title(self) -> None:
        """F3: a heading whose title is ONLY a math span exercises the
        leading+trailing empty-string parity edge; math survives, the
        underscore is NOT escaped."""
        out = _build_latex_wrapper("## $x_i$")
        assert "\\subsection{$x_i$}" in out
        assert "x\\_i" not in out

    def test_display_math_in_heading_preserved(self) -> None:
        """F3: display $$...$$ math inside a heading title is preserved
        byte-for-byte (not escaped)."""
        out = _build_latex_wrapper("## sum $$\\sum_i x_i$$ done")
        assert "$$\\sum_i x_i$$" in out
        # The subscript inside the display math is untouched.
        assert "\\sum_i x_i" in out
        assert "\\subsection{" in out

    # -- textbook-render-robustness-m1: \begin/\end{array} balance --

    def test_orphaned_end_array_dropped(self) -> None:
        """The 1404.3143 case: MinerU dropped all \\begin{array} but kept
        \\end{array} closers. Orphaned closers must be removed so LaTeXML
        does not 'close boxing group' and abort the document."""
        body = "prose $x$\n$$ a + b \\end{array} $$\nmore prose"
        out = _build_latex_wrapper(body)
        assert "\\end{array}" not in out
        assert "more prose" in out

    def test_balanced_array_untouched(self) -> None:
        """A balanced array (even inside $$) nets zero and is preserved."""
        body = "$$\\begin{array}{cc} a & b \\\\ c & d \\end{array}$$"
        out = _build_latex_wrapper(body)
        assert "\\begin{array}{cc}" in out
        assert "\\end{array}" in out
        # Exactly one of each survives (no spurious append/drop).
        assert out.count("\\begin{array}") == 1
        assert out.count("\\end{array}") == 1

    def test_nested_arrays_untouched(self) -> None:
        """Depth counter handles nesting: a balanced nested pair is kept."""
        body = (
            "$$\\begin{array}{c}\\begin{array}{cc} x & y \\end{array}"
            "\\end{array}$$"
        )
        out = _build_latex_wrapper(body)
        assert out.count("\\begin{array}") == 2
        assert out.count("\\end{array}") == 2

    def test_unclosed_begin_array_dropped(self) -> None:
        """F1: an unclosed \\begin{array} is DROPPED, not closed with an
        appended \\end{array} — an appended closer would land in text mode
        outside the (already-closed) $$ and re-create the 'close boxing group'
        fatal the sanitizer exists to prevent."""
        body = "$$\\begin{array}{c} a \\\\ b $$\ntrailing prose"
        out = _build_latex_wrapper(body)
        assert "\\begin{array}" not in out
        assert "\\end{array}" not in out
        assert "trailing prose" in out

    def test_orphaned_closer_leaves_alignment_residue(self) -> None:
        """F2 (pinned): dropping an orphaned \\end{array} removes only the
        token; the array body's & / \\\\ residue is intentionally left in the
        surrounding math (LaTeXML error-recovers a stray &). Pins the accepted
        degraded-but-renders behavior so a future change is deliberate."""
        body = "$$ a & b \\\\ c & d \\end{array} $$"
        out = _build_latex_wrapper(body)
        assert "\\end{array}" not in out
        assert "a & b" in out  # residue retained (accepted limitation)

    def test_literal_end_array_in_heading_is_dropped(self) -> None:
        """F3 (pinned): sanitize runs on raw markdown (step 0), so a literal
        \\end{array} token in a heading TITLE is treated as a math token and
        dropped — a known limitation of the coarse global token scan. Pinned
        so the behavior is asserted, not a silent surprise."""
        out = _build_latex_wrapper("## The \\end{array} trick")
        assert "\\subsection{" in out
        assert "\\end{array}" not in out
        assert "trick" in out

    def test_array_balance_composes_with_headings(self) -> None:
        """Sanitization (step 0) must not break heading conversion (step 1):
        an orphaned \\end{array} is dropped AND headings still convert."""
        body = "# Title\n\n$$ z \\end{array} $$\n\n## Section"
        out = _build_latex_wrapper(body)
        assert "\\section{Title}" in out
        assert "\\subsection{Section}" in out
        assert "\\end{array}" not in out


class TestRenderTimeoutThreading:
    """textbook-render-robustness-m1: render passes the configured timeout."""

    def test_render_passes_configured_latexml_timeout(
        self, tmp_path: Path,
    ) -> None:
        mineru_result = _build_minimal_mineru_result(tmp_path)
        parsed_dir = tmp_path / "parsed"
        parsed_dir.mkdir()

        def fake_parse(main_tex, parsed_dir, paper_id, timeout=None):  # noqa: ARG001
            out_dir = parsed_dir / paper_id
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "index.html").write_text("<html></html>")
            return None

        with patch.object(
            textbook_renderer, "parse_with_latexml", side_effect=fake_parse,
        ) as mock:
            render_mineru_to_html(mineru_result, parsed_dir, "textbook:b")

        _, kwargs = mock.call_args
        assert kwargs["timeout"] == textbook_renderer._CONFIGURED_LATEXML_TIMEOUT_S


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
        def fake_parse(main_tex, parsed_dir, paper_id, timeout=None):  # noqa: ARG001
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

        def fake_parse(main_tex, parsed_dir, paper_id, timeout=None):  # noqa: ARG001
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

        def fake_parse(main_tex, parsed_dir, paper_id, timeout=None):  # noqa: ARG001
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

        def fake_parse(main_tex, parsed_dir, paper_id, timeout=None):  # noqa: ARG001
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

        def fake_parse(main_tex, parsed_dir, paper_id, timeout=None):  # noqa: ARG001
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

    def test_multi_class_ltx_error_counted(self, tmp_path: Path) -> None:
        """m6 F6: ltx_ERROR as a token within a multi-class attribute
        (or on a <span>, or single-quoted) must be counted."""
        mineru_result = _build_minimal_mineru_result(tmp_path)
        parsed_dir = tmp_path / "parsed"
        parsed_dir.mkdir()

        def fake_parse(main_tex, parsed_dir, paper_id, timeout=None):  # noqa: ARG001
            out_dir = parsed_dir / paper_id
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "index.html").write_text(
                "<!DOCTYPE html><html><body>"
                '<span class="ltx_ERROR ltx_font_bold">e1</span>'
                "<math class='ltx_ERROR'>e2</math>"  # single-quoted
                '<math class="ltx_Math">ok</math>'
                "</body></html>",
                encoding="utf-8",
            )
            return None

        with patch.object(
            textbook_renderer, "parse_with_latexml", side_effect=fake_parse,
        ):
            result = render_mineru_to_html(
                mineru_result, parsed_dir, "textbook:my-book",
            )
        # Two ltx_ERROR tokens (multi-class span + single-quoted math).
        assert result.latex_error_annotations == 2

    def test_symlink_in_images_not_dereferenced(
        self, tmp_path: Path,
    ) -> None:
        """m6 F5: a symlink under MinerU's images/ must be PRESERVED
        (not dereferenced), so external target content is never copied
        into the notebook tree."""
        mineru_result = _build_minimal_mineru_result(tmp_path)
        pdf_stem = mineru_result.markdown_path.stem
        images_dir = mineru_result.output_dir / pdf_stem / "auto" / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        # Plant a symlink pointing outside the notebook tree.
        secret = tmp_path / "secret.txt"
        secret.write_text("SENSITIVE", encoding="utf-8")
        (images_dir / "evil.png").symlink_to(secret)
        parsed_dir = tmp_path / "parsed"
        parsed_dir.mkdir()

        def fake_parse(main_tex, parsed_dir, paper_id, timeout=None):  # noqa: ARG001
            (parsed_dir / paper_id).mkdir(parents=True, exist_ok=True)
            (parsed_dir / paper_id / "index.html").write_text("<html></html>")
            return None

        with patch.object(
            textbook_renderer, "parse_with_latexml", side_effect=fake_parse,
        ):
            result = render_mineru_to_html(
                mineru_result, parsed_dir, "textbook:my-book",
            )
        dest = result.output_html_path.parent / "images" / "evil.png"
        # The entry is preserved as a symlink, NOT a regular file with
        # the dereferenced secret content.
        assert dest.is_symlink()
        # Reading it would follow the symlink, but the COPIED tree
        # never contains a regular file holding 'SENSITIVE'.
        copied_regular_files = [
            p for p in (result.output_html_path.parent / "images").iterdir()
            if p.is_file() and not p.is_symlink()
        ]
        assert copied_regular_files == []


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
