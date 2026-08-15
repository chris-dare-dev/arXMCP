"""Tests for the shipped MinerU Stage-1 CLI (ingest-robustness-m1 AC2).

The MinerU + LaTeXML seam (``run_mineru_sandboxed`` / ``render_mineru_to_html``)
is MOCKED so no real GPU/LaTeXML run occurs; the render mock writes a stub
``parsed/<flat>/index.html`` so the post-parse existence check passes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools import notebook_pdf_parse
from tools._notebook_common import REPO_ROOT, NotebookError

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


# --- exit-code contract -----------------------------------------------------
# The `run()` tests above assert the PURE function's return value. These assert
# the value that actually reaches the shell, which is what a pipeline chaining
# `&& tools/notebook_textbook_ingest.py` gates on. Without them, a regression
# in main()'s return path or the `SystemExit(main())` entry point would make a
# failed parse look like success with every `run()` test still green.


def test_main_returns_1_on_failed_parse(tmp_path):
    """A parse error must propagate through main() as exit status 1."""
    nb = _setup_nb(tmp_path)
    with (
        patch("tools.notebook_pdf_parse.notebook_dir", return_value=nb),
        patch(
            "tools.notebook_pdf_parse.run_mineru_sandboxed",
            side_effect=RuntimeError("mineru exploded"),
        ),
    ):
        rc = notebook_pdf_parse.main(["my-notebook", "--paper-id", FLAT])
    assert rc == 1


def test_main_returns_1_on_missing_pdf(tmp_path):
    nb = _setup_nb(tmp_path, with_pdf=False)
    with patch("tools.notebook_pdf_parse.notebook_dir", return_value=nb):
        rc = notebook_pdf_parse.main(["my-notebook", "--paper-id", FLAT])
    assert rc == 1


def test_main_returns_1_on_partial_batch_failure(tmp_path):
    """One failure out of two papers is still a non-zero exit."""
    nb = _setup_nb(tmp_path)
    (nb / "pdfs" / "2401.00001.pdf").write_bytes(b"%PDF-1.4 fake")

    def _mineru(pdf_path, output_dir, timeout_s=None):  # noqa: ANN001, ARG001
        if "2602.24016" in str(pdf_path):
            raise RuntimeError("mineru exploded")
        return MagicMock()

    with (
        patch("tools.notebook_pdf_parse.notebook_dir", return_value=nb),
        patch("tools.notebook_pdf_parse.run_mineru_sandboxed", side_effect=_mineru),
        patch(
            "tools.notebook_pdf_parse.render_mineru_to_html",
            side_effect=_render_writes_index(),
        ),
    ):
        rc = notebook_pdf_parse.main(
            ["my-notebook", "--paper-id", FLAT, "--paper-id", "2401.00001"]
        )
    assert rc == 1
    assert (nb / "parsed" / "2401.00001" / "index.html").is_file()


def test_module_entry_point_raises_systemexit_with_main_rc():
    """`__main__` must hand main()'s code to the interpreter, not swallow it.

    Pins the `raise SystemExit(main())` tail of the module: a bare `main()`
    call there would exit 0 on every failure.
    """
    source = Path(notebook_pdf_parse.__file__).read_text(encoding="utf-8")
    assert "raise SystemExit(main())" in source


def test_process_exit_status_is_1_on_failed_parse(tmp_path):
    """End-to-end: a real subprocess run of the CLI exits 1 on a parse failure.

    No mocking and no mineru binary needed — a notebook with no staged PDF is a
    per-paper failure on the same aggregation path. This is the only test that
    observes the status the SHELL sees.
    """
    data_dir = tmp_path / "datadir"
    (data_dir / "notebooks" / "exit-code-nb" / "pdfs").mkdir(parents=True)
    (data_dir / "notebooks" / "exit-code-nb" / "parsed").mkdir(parents=True)

    env = dict(os.environ)
    env["ARXMCP_DATA_DIR"] = str(data_dir)
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "notebook_pdf_parse.py"),
            "exit-code-nb",
            "--paper-id",
            FLAT,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 1, (
        f"expected exit 1 on a failed parse, got {proc.returncode}\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    assert "fail=1" in proc.stdout


# --- --timeout-s range validation -------------------------------------------


@pytest.mark.parametrize("bad", ["5400", "59", "0", "-1", "abc"])
def test_out_of_range_timeout_is_argparse_error(bad, capsys):
    """An out-of-range --timeout-s is a USAGE error (exit 2), not a parse failure.

    Before this guard the value reached `run_mineru_sandboxed`, which raised
    RuntimeError, which `_parse_one` aggregated as a per-paper parse failure —
    reporting a bad flag as if the PDF were unparseable.
    """
    with pytest.raises(SystemExit) as excinfo:
        notebook_pdf_parse.main(["my-notebook", "--paper-id", FLAT, "--timeout-s", bad])
    assert excinfo.value.code == 2
    assert "timeout-s" in capsys.readouterr().err


@pytest.mark.parametrize("good", [60, 1800, 3600])
def test_in_range_timeout_is_accepted(good):
    args = notebook_pdf_parse._build_arg_parser().parse_args(
        ["my-notebook", "--paper-id", FLAT, "--timeout-s", str(good)]
    )
    assert args.timeout_s == good


def test_timeout_bounds_track_the_parser_module():
    """The CLI bound must be the parser's bound, never a restated literal."""
    from ingest import textbook_parser

    parser = notebook_pdf_parse._build_arg_parser()
    action = next(a for a in parser._actions if a.dest == "timeout_s")
    assert action.type is notebook_pdf_parse._timeout_arg
    assert notebook_pdf_parse._TIMEOUT_MIN_S is textbook_parser._TIMEOUT_MIN_S
    assert notebook_pdf_parse._TIMEOUT_MAX_S is textbook_parser._TIMEOUT_MAX_S
