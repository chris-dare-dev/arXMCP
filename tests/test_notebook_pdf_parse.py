"""Tests for the shipped MinerU Stage-1 CLI (ingest-robustness-m1 AC2).

The MinerU + LaTeXML seam (``run_mineru_sandboxed`` / ``render_mineru_to_html``)
is MOCKED so no real GPU/LaTeXML run occurs; the render mock writes a stub
``parsed/<flat>/index.html`` so the post-parse existence check passes.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools import notebook_pdf_parse
from tools._notebook_common import NotebookError

FLAT = "2602.24016"  # an arXiv id has no slash/colon, so flat == id


def _setup_nb(tmp_path: Path, *, with_pdf: bool = True) -> Path:
    nb = tmp_path / "nb"
    (nb / "pdfs").mkdir(parents=True)
    (nb / "parsed").mkdir(parents=True)
    if with_pdf:
        (nb / "pdfs" / f"{FLAT}.pdf").write_bytes(b"%PDF-1.4 fake pdf")
    return nb


def _render_writes_index():
    """A render mock that writes the stub index.html the CLI checks for."""

    def _render(result, parsed_dir, paper_id):  # noqa: ANN001, ARG001
        flat = notebook_pdf_parse._flat_paper_id(paper_id)
        out = Path(parsed_dir) / flat
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.html").write_text("<html><math/></html>", encoding="utf-8")
        return MagicMock()

    return _render


def test_happy_path_parses_pdf(tmp_path):
    nb = _setup_nb(tmp_path)
    with (
        patch("tools.notebook_pdf_parse.notebook_dir", return_value=nb),
        patch(
            "tools.notebook_pdf_parse.run_mineru_sandboxed",
            return_value=MagicMock(),
        ) as m_mineru,
        patch(
            "tools.notebook_pdf_parse.render_mineru_to_html",
            side_effect=_render_writes_index(),
        ) as m_render,
    ):
        rc = notebook_pdf_parse.run("my-notebook", [FLAT])
    assert rc == 0
    assert m_mineru.called
    assert m_render.called
    assert (nb / "parsed" / FLAT / "index.html").is_file()


def test_idempotent_skip_when_index_exists(tmp_path):
    nb = _setup_nb(tmp_path)
    idx = nb / "parsed" / FLAT / "index.html"
    idx.parent.mkdir(parents=True)
    idx.write_text("<html/>", encoding="utf-8")
    with (
        patch("tools.notebook_pdf_parse.notebook_dir", return_value=nb),
        patch("tools.notebook_pdf_parse.run_mineru_sandboxed") as m_mineru,
        patch("tools.notebook_pdf_parse.render_mineru_to_html") as m_render,
    ):
        rc = notebook_pdf_parse.run("my-notebook", [FLAT])
    assert rc == 0
    assert not m_mineru.called
    assert not m_render.called


def test_force_reparses_existing(tmp_path):
    nb = _setup_nb(tmp_path)
    idx = nb / "parsed" / FLAT / "index.html"
    idx.parent.mkdir(parents=True)
    idx.write_text("<html/>", encoding="utf-8")
    with (
        patch("tools.notebook_pdf_parse.notebook_dir", return_value=nb),
        patch(
            "tools.notebook_pdf_parse.run_mineru_sandboxed",
            return_value=MagicMock(),
        ) as m_mineru,
        patch(
            "tools.notebook_pdf_parse.render_mineru_to_html",
            side_effect=_render_writes_index(),
        ),
    ):
        rc = notebook_pdf_parse.run("my-notebook", [FLAT], force=True)
    assert rc == 0
    assert m_mineru.called


def test_missing_pdf_is_clean_failure(tmp_path):
    nb = _setup_nb(tmp_path, with_pdf=False)
    with (
        patch("tools.notebook_pdf_parse.notebook_dir", return_value=nb),
        patch("tools.notebook_pdf_parse.run_mineru_sandboxed") as m_mineru,
    ):
        rc = notebook_pdf_parse.run("my-notebook", [FLAT])
    assert rc == 1
    assert not m_mineru.called


def test_invalid_paper_id_raises(tmp_path):
    nb = _setup_nb(tmp_path)
    with (
        patch("tools.notebook_pdf_parse.notebook_dir", return_value=nb),
        pytest.raises(NotebookError, match="invalid paper_id"),
    ):
        notebook_pdf_parse.run("my-notebook", ["not a valid id!!"])


def test_timeout_is_clean_per_paper_failure(tmp_path):
    # H2 (arxmcp critique): run_mineru_sandboxed RE-RAISES
    # subprocess.TimeoutExpired on the wall-clock cap; the CLI must aggregate it
    # as a per-paper failure, not abort the batch. Two papers: the first times
    # out, the second must still parse.
    import subprocess

    nb = _setup_nb(tmp_path)  # stages the 2602.24016 PDF
    (nb / "pdfs" / "2401.00001.pdf").write_bytes(b"%PDF-1.4 fake")
    calls = {"n": 0}

    def _mineru(pdf_path, output_dir, timeout_s=None):
        calls["n"] += 1
        if "2602.24016" in str(pdf_path):
            raise subprocess.TimeoutExpired(cmd="mineru", timeout=1)
        return MagicMock()

    with (
        patch("tools.notebook_pdf_parse.notebook_dir", return_value=nb),
        patch("tools.notebook_pdf_parse.run_mineru_sandboxed", side_effect=_mineru),
        patch(
            "tools.notebook_pdf_parse.render_mineru_to_html",
            side_effect=_render_writes_index(),
        ),
    ):
        rc = notebook_pdf_parse.run("my-notebook", ["2602.24016", "2401.00001"])
    assert rc == 1  # the timed-out paper is recorded as a failure
    assert calls["n"] == 2  # the batch CONTINUED to the second paper (no abort)
    assert (nb / "parsed" / "2401.00001" / "index.html").is_file()  # 2nd parsed


def test_main_no_paper_id_returns_2(capsys):
    rc = notebook_pdf_parse.main(["my-notebook"])
    assert rc == 2
    assert "paper-id" in capsys.readouterr().err
