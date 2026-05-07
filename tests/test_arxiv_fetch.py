"""Unit tests for `tools.arxiv_fetch` — the offline-testable surface.

The actual `/e-print/` HTTP fetch and the `latexmlc` invocation are
network/binary dependencies that Phase 4 exercises after user
authorization. Everything else lives here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.arxiv_fetch import (
    DEFAULT_503_BACKOFF_SECONDS,
    MIN_PARSED_HTML_BYTES,
    build_user_agent,
    detect_parse_success,
    find_main_tex,
    is_tar_archive,
    parse_retry_after,
    validate_paper_id,
)


class TestUserAgent:
    def test_builds_from_env(self, monkeypatch):
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "alice@example.com")
        assert build_user_agent() == "arXMCP/0.1 (mailto:alice@example.com)"

    def test_explicit_overrides_env(self, monkeypatch):
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "alice@example.com")
        assert build_user_agent("bob@example.com") == "arXMCP/0.1 (mailto:bob@example.com)"

    def test_missing_email_raises(self, monkeypatch):
        monkeypatch.delenv("ARXMCP_CONTACT_EMAIL", raising=False)
        with pytest.raises(RuntimeError, match="ARXMCP_CONTACT_EMAIL"):
            build_user_agent()


class TestPaperIdValidation:
    @pytest.mark.parametrize("pid", ["2307.01156", "1812.04567", "2401.00001", "9912.99999"])
    def test_accepts_new_style(self, pid):
        validate_paper_id(pid)

    @pytest.mark.parametrize(
        "pid",
        [
            "math.AG/0612345",   # old-style — out of scope
            "2307.123",          # too short
            "2307.0115678",      # too long (7 digits)
            "23.0701156",        # wrong YYMM shape
            "abcd.efghi",        # non-numeric
            "",                  # empty
            "2307.01156v3",      # version suffix not allowed in this layer
        ],
    )
    def test_rejects_invalid(self, pid):
        with pytest.raises(ValueError):
            validate_paper_id(pid)


class TestContentTypeDispatch:
    @pytest.mark.parametrize(
        "ct",
        [
            "application/x-eprint-tar",
            "application/x-eprint-tar; charset=binary",
            "APPLICATION/X-EPRINT-TAR",
        ],
    )
    def test_tar_detected(self, ct):
        assert is_tar_archive(ct) is True

    @pytest.mark.parametrize(
        "ct",
        [
            "application/x-eprint",
            "application/gzip",
            "application/octet-stream",
            "",
            None,
        ],
    )
    def test_non_tar_returns_false(self, ct):
        assert is_tar_archive(ct) is False


class TestRetryAfter:
    def test_returns_default_when_missing(self):
        assert parse_retry_after(None, 30.0) == 30.0

    def test_returns_default_when_unparseable(self):
        assert parse_retry_after("soon", 30.0) == 30.0

    def test_honors_value_when_above_default(self):
        assert parse_retry_after("60", 30.0) == 60.0

    def test_clamps_below_default(self):
        # Server says wait 5s, our default floor is 30 — we use 30.
        # Politeness floor never goes below DEFAULT_503_BACKOFF_SECONDS.
        assert parse_retry_after("5", DEFAULT_503_BACKOFF_SECONDS) == DEFAULT_503_BACKOFF_SECONDS


class TestParseSuccessDetector:
    """The four-part rule from research synthesis D4 — silent math loss is the
    single failure mode this test guards against."""

    def _make_html(self, tmp_path: Path, paper_id: str, body: str) -> Path:
        out_dir = tmp_path / paper_id
        out_dir.mkdir()
        out = out_dir / "index.html"
        out.write_text(body)
        return out

    def test_all_four_conditions_pass(self, tmp_path):
        body = "<html>" + ("x" * (MIN_PARSED_HTML_BYTES + 100)) + " <math>e</math></html>"
        out = self._make_html(tmp_path, "2307.01156", body)
        result = detect_parse_success(out, exit_code=0)
        assert result.success is True
        assert result.mathml_node_count == 1

    def test_silent_math_loss_caught(self, tmp_path):
        # exit 0, file present, big enough — but no <math> tag.
        body = "<html>" + ("x" * (MIN_PARSED_HTML_BYTES + 100)) + "</html>"
        out = self._make_html(tmp_path, "2307.01156", body)
        result = detect_parse_success(out, exit_code=0)
        assert result.success is False
        assert "no <math> nodes" in result.message

    def test_too_small_caught(self, tmp_path):
        body = "<html><math>e</math></html>"  # has math but tiny
        out = self._make_html(tmp_path, "2307.01156", body)
        result = detect_parse_success(out, exit_code=0)
        assert result.success is False
        assert "too small" in result.message

    def test_nonzero_exit_caught(self, tmp_path):
        body = "<html>" + ("x" * (MIN_PARSED_HTML_BYTES + 100)) + " <math>e</math></html>"
        out = self._make_html(tmp_path, "2307.01156", body)
        result = detect_parse_success(out, exit_code=2)
        assert result.success is False
        assert "exit_code=2" in result.message

    def test_missing_output_caught(self, tmp_path):
        out = tmp_path / "2307.01156" / "index.html"
        result = detect_parse_success(out, exit_code=0)
        assert result.success is False
        assert "missing" in result.message

    def test_counts_multiple_math_nodes(self, tmp_path):
        body = (
            "<html>"
            + ("x" * (MIN_PARSED_HTML_BYTES + 100))
            + "<math>a</math><math display='block'>b</math><math>c</math></html>"
        )
        out = self._make_html(tmp_path, "2307.01156", body)
        result = detect_parse_success(out, exit_code=0)
        assert result.mathml_node_count == 3


class TestFindMainTex:
    def test_unique_tex_returned(self, tmp_path):
        d = tmp_path / "2307.01156"
        d.mkdir()
        only = d / "main.tex"
        only.write_text("hello")
        assert find_main_tex(d, "2307.01156") == only

    def test_paper_id_filename_preferred(self, tmp_path):
        d = tmp_path / "2307.01156"
        d.mkdir()
        (d / "appendix.tex").write_text("appendix")
        target = d / "2307.01156.tex"
        target.write_text("\\documentclass{amsart}")
        assert find_main_tex(d, "2307.01156") == target

    def test_documentclass_heuristic(self, tmp_path):
        d = tmp_path / "2307.01156"
        d.mkdir()
        (d / "appendix.tex").write_text("appendix only — no documentclass here")
        main = d / "main.tex"
        main.write_text("\\documentclass{amsart}\n\\begin{document}...\\end{document}")
        assert find_main_tex(d, "2307.01156") == main

    def test_falls_back_to_first_alphabetical(self, tmp_path):
        d = tmp_path / "2307.01156"
        d.mkdir()
        (d / "z.tex").write_text("no documentclass")
        (d / "a.tex").write_text("no documentclass")
        assert find_main_tex(d, "2307.01156") == d / "a.tex"

    def test_no_tex_returns_none(self, tmp_path):
        d = tmp_path / "2307.01156"
        d.mkdir()
        (d / "README").write_text("not tex")
        assert find_main_tex(d, "2307.01156") is None
