"""Regression tests for E01_S01-S03 critique findings.

Each test class anchors a specific finding from
`.claude/notes/milestones/E01_S01-S03/critique-merged.md`. If a future
refactor reintroduces the issue, the corresponding test fires.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools import fetch_seed
from tools.arxiv_fetch import (
    MAX_RESPONSE_BYTES,
    FetchResult,
    ParseResult,
    _extract_eprint_response,
    _safe_extract,
    fetch_eprint,
    parse_with_latexml,
)
from tools.fetch_seed import (
    EXPECTED_SEED_COUNT,
    Outcome,
    already_parsed,
    fetch_with_backoff,
    process_paper,
)


class TestF1MainTexSelection:
    """F1 — process_paper must use FetchResult.main_tex (the heuristic),
    not rglob's first match. Multi-tex submissions break otherwise."""

    def test_process_paper_uses_fetchresult_main_tex(self, tmp_path: Path, monkeypatch):
        paper_id = "2307.01156"
        raw_paper = tmp_path / "raw" / paper_id
        raw_paper.mkdir(parents=True)
        appendix = raw_paper / "appendix.tex"
        appendix.write_text("appendix content, no documentclass")
        main = raw_paper / f"{paper_id}.tex"
        main.write_text("\\documentclass{amsart}\\begin{document}body\\end{document}")

        monkeypatch.setattr(fetch_seed, "RAW_DIR", tmp_path / "raw")
        monkeypatch.setattr(fetch_seed, "PARSED_DIR", tmp_path / "parsed")

        fake_result = FetchResult(
            paper_id=paper_id,
            raw_dir=raw_paper,
            main_tex=main,  # the heuristic returns the right file
            http_status=200,
            bytes_downloaded=1024,
            archive_kind="tar",
        )
        observed_tex_paths: list[Path] = []

        def fake_parse(main_tex, parsed_dir, pid, **kwargs):
            observed_tex_paths.append(main_tex)
            return ParseResult(
                paper_id=pid,
                success=True,
                exit_code=0,
                output_path=parsed_dir / pid / "index.html",
                file_size=2048,
                mathml_node_count=3,
                message="ok",
            )

        monkeypatch.setattr(
            fetch_seed,
            "fetch_with_backoff",
            lambda pid, raw_dir: (
                Outcome(paper_id=pid, success=True, message="fetched", elapsed_s=1.0),
                fake_result,
            ),
        )
        monkeypatch.setattr(fetch_seed, "parse_with_latexml", fake_parse)

        outcome = process_paper(paper_id)
        assert outcome.success is True
        assert observed_tex_paths == [main]  # NOT appendix.tex

    def test_falls_back_to_find_main_tex_if_fetchresult_lacks_it(
        self, tmp_path: Path, monkeypatch
    ):
        """Belt-and-braces: if FetchResult.main_tex is None, the loop
        still recovers by calling find_main_tex on the raw_dir."""
        paper_id = "2307.01156"
        raw_paper = tmp_path / "raw" / paper_id
        raw_paper.mkdir(parents=True)
        main = raw_paper / f"{paper_id}.tex"
        main.write_text("\\documentclass{amsart}")

        monkeypatch.setattr(fetch_seed, "RAW_DIR", tmp_path / "raw")
        monkeypatch.setattr(fetch_seed, "PARSED_DIR", tmp_path / "parsed")

        fake_result = FetchResult(
            paper_id=paper_id,
            raw_dir=raw_paper,
            main_tex=None,  # heuristic somehow returned None
            http_status=200,
            bytes_downloaded=1024,
            archive_kind="tar",
        )
        observed: list[Path] = []
        monkeypatch.setattr(
            fetch_seed,
            "fetch_with_backoff",
            lambda pid, raw_dir: (
                Outcome(paper_id=pid, success=True, message="fetched", elapsed_s=1.0),
                fake_result,
            ),
        )
        monkeypatch.setattr(
            fetch_seed,
            "parse_with_latexml",
            lambda mt, pd, pid, **kw: (
                observed.append(mt),
                ParseResult(pid, True, 0, pd / pid / "index.html", 2048, 3, "ok"),
            )[1],
        )

        process_paper(paper_id)
        assert observed == [main]


class TestF2ExceptionEscape:
    """F2 — TimeoutExpired and tarfile errors must NOT escape process_paper."""

    def test_latexml_timeout_caught(self, tmp_path: Path, monkeypatch):
        paper_id = "2307.01156"
        raw_paper = tmp_path / "raw" / paper_id
        raw_paper.mkdir(parents=True)
        main = raw_paper / f"{paper_id}.tex"
        main.write_text("\\documentclass{amsart}")

        monkeypatch.setattr(fetch_seed, "RAW_DIR", tmp_path / "raw")
        monkeypatch.setattr(fetch_seed, "PARSED_DIR", tmp_path / "parsed")

        fake_result = FetchResult(
            paper_id=paper_id,
            raw_dir=raw_paper,
            main_tex=main,
            http_status=200,
            bytes_downloaded=1024,
            archive_kind="tar",
        )

        def boom(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=["latexmlc"], timeout=300)

        monkeypatch.setattr(
            fetch_seed,
            "fetch_with_backoff",
            lambda pid, raw_dir: (
                Outcome(paper_id=pid, success=True, message="fetched", elapsed_s=1.0),
                fake_result,
            ),
        )
        monkeypatch.setattr(fetch_seed, "parse_with_latexml", boom)

        outcome = process_paper(paper_id)
        assert outcome.success is False
        assert "TimeoutExpired" in outcome.message

    def test_tarfile_error_caught(self, tmp_path: Path, monkeypatch):
        """A corrupt tarball mid-corpus must not kill the loop."""
        monkeypatch.setattr(fetch_seed, "RAW_DIR", tmp_path / "raw")

        def fake_fetch_eprint(paper_id, raw_dir, **kwargs):
            raise tarfile.ReadError("not a gzip file")

        monkeypatch.setattr(fetch_seed, "fetch_eprint", fake_fetch_eprint)

        outcome, result = fetch_with_backoff("2307.01156", tmp_path / "raw")
        assert outcome.success is False
        assert "ReadError" in outcome.message
        assert result is None


class TestF3UndersizedSeedList:
    """F3 — fetch_seed.py must exit 2 on an undersized seed list,
    unless --allow-undersized is passed."""

    def test_undersized_exits_2(self, tmp_path: Path, monkeypatch, capsys):
        seed = tmp_path / "seed.txt"
        seed.write_text("2307.01156\n")  # 1 ID, not 50
        monkeypatch.setattr("sys.argv", ["fetch_seed.py", "--seed-file", str(seed)])
        rc = fetch_seed.main()
        assert rc == 2
        captured = capsys.readouterr()
        assert "expected" in captured.err
        assert str(EXPECTED_SEED_COUNT) in captured.err

    def test_allow_undersized_proceeds(self, tmp_path: Path, monkeypatch):
        seed = tmp_path / "seed.txt"
        seed.write_text("2307.01156\n")
        monkeypatch.setattr(
            "sys.argv", ["fetch_seed.py", "--seed-file", str(seed), "--allow-undersized"]
        )
        # Mock process_paper so we don't actually network/parse.
        monkeypatch.setattr(
            fetch_seed,
            "process_paper",
            lambda pid: Outcome(pid, True, "mocked", 0.0),
        )
        # Mock log writer to avoid touching the real var/arxmcp/.
        monkeypatch.setattr(fetch_seed, "write_log", lambda *a, **kw: None)
        # Mock politeness sleep so the test is fast.
        monkeypatch.setattr(fetch_seed, "politeness_sleep", lambda *a, **kw: None)

        rc = fetch_seed.main()
        # 1 success out of 1 — below the 45/50 threshold but the override flag
        # should at least let us reach the threshold check (return 1, not 2).
        assert rc != 2  # didn't hit the undersized gate


class TestIS3IdempotencyGate:
    """IS3 — process_paper must skip papers already parsed."""

    def test_already_parsed_returns_skipped(self, tmp_path: Path, monkeypatch):
        paper_id = "2307.01156"
        parsed_dir = tmp_path / "parsed"
        out_dir = parsed_dir / paper_id
        out_dir.mkdir(parents=True)
        # Create a "clean" parsed HTML > MIN_PARSED_HTML_BYTES.
        (out_dir / "index.html").write_text("<html>" + "x" * 4096 + "</html>")

        monkeypatch.setattr(fetch_seed, "PARSED_DIR", parsed_dir)
        called: list = []
        monkeypatch.setattr(
            fetch_seed, "fetch_with_backoff",
            lambda *a, **kw: called.append(("fetched",)) or None,
        )

        outcome = process_paper(paper_id)
        assert outcome.success is True
        assert outcome.message == "already parsed (skipped)"
        assert outcome.elapsed_s == 0.0
        # Network was NOT touched:
        assert called == []

    def test_undersized_or_missing_html_does_not_skip(self, tmp_path: Path):
        parsed_dir = tmp_path / "parsed"
        # No HTML: not skipped.
        assert already_parsed("2307.01156", parsed_dir) is False
        # Tiny HTML: not skipped.
        (parsed_dir / "2307.01156").mkdir(parents=True)
        (parsed_dir / "2307.01156" / "index.html").write_text("tiny")
        assert already_parsed("2307.01156", parsed_dir) is False


class TestF6SafeExtract:
    """F6 — _safe_extract must reject path-traversal members."""

    def test_rejects_dotdot_member(self, tmp_path: Path):
        tar_bytes = io.BytesIO()
        with tarfile.open(fileobj=tar_bytes, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="../../etc/passwd")
            info.size = 5
            tar.addfile(info, io.BytesIO(b"hello"))
        tar_bytes.seek(0)

        with (
            tarfile.open(fileobj=tar_bytes, mode="r:gz") as tar,
            pytest.raises(RuntimeError, match="refusing to extract"),
        ):
            _safe_extract(tar, tmp_path)

        # Nothing was created outside dest:
        assert not (tmp_path.parent.parent / "etc" / "passwd").exists()

    def test_accepts_normal_member(self, tmp_path: Path):
        tar_bytes = io.BytesIO()
        with tarfile.open(fileobj=tar_bytes, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="paper.tex")
            content = b"\\documentclass{amsart}"
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        tar_bytes.seek(0)

        with tarfile.open(fileobj=tar_bytes, mode="r:gz") as tar:
            _safe_extract(tar, tmp_path)
        assert (tmp_path / "paper.tex").exists()
        assert (tmp_path / "paper.tex").read_bytes() == b"\\documentclass{amsart}"


class TestF6ParseWithLatexml:
    """F6 — parse_with_latexml must surface configuration failures cleanly."""

    def test_missing_latexmlc_raises_clear_error(self, tmp_path: Path, monkeypatch):
        main = tmp_path / "main.tex"
        main.write_text("\\documentclass{amsart}")
        monkeypatch.setattr("shutil.which", lambda name: None)
        with pytest.raises(RuntimeError, match="latexmlc not on PATH"):
            parse_with_latexml(main, tmp_path / "parsed", "2307.01156")

    def test_nonzero_exit_returns_failure_parseresult(self, tmp_path: Path, monkeypatch):
        main = tmp_path / "main.tex"
        main.write_text("\\documentclass{amsart}")
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/latexmlc")

        # E13_S03 — parse_with_latexml now uses subprocess.Popen +
        # start_new_session=True for process-group kill discipline,
        # not subprocess.run. Mock Popen instead.
        class FakeProc:
            def __init__(self, *args, **kwargs):
                self.pid = 12345
                self.returncode = 1

            def communicate(self, timeout=None):
                return ("", "")

        monkeypatch.setattr(subprocess, "Popen", FakeProc)
        result = parse_with_latexml(main, tmp_path / "parsed", "2307.01156")
        assert result.success is False
        assert result.exit_code == 1


class TestF8ResponseSizeCap:
    """F8 — fetch_eprint must refuse responses larger than MAX_RESPONSE_BYTES."""

    def test_content_length_over_cap_rejected(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")
        fake_resp = MagicMock()
        fake_resp.headers.get = lambda key, default=None: {
            "Content-Type": "application/x-eprint-tar",
            "Content-Length": str(MAX_RESPONSE_BYTES + 1),
        }.get(key, default)
        fake_resp.status = 200
        fake_resp.read = lambda *a: b""
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda *a: None

        with (
            patch("urllib.request.urlopen", return_value=fake_resp),
            pytest.raises(RuntimeError, match="response too large"),
        ):
            fetch_eprint("2307.01156", tmp_path)

    def test_oversized_body_rejected_when_no_content_length(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")
        fake_resp = MagicMock()
        fake_resp.headers.get = lambda key, default=None: {
            "Content-Type": "application/x-eprint-tar",
        }.get(key, default)
        fake_resp.status = 200
        fake_resp.read = lambda n: b"x" * (MAX_RESPONSE_BYTES + 1)
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda *a: None

        with (
            patch("urllib.request.urlopen", return_value=fake_resp),
            pytest.raises(RuntimeError, match="cap exceeded mid-read"),
        ):
            fetch_eprint("2307.01156", tmp_path)


class TestEprintSniff:
    """Smoke-test follow-up: live arXiv response had a non-tar Content-Type
    but the gzip-decompressed body WAS a tar. The dispatch must sniff bytes,
    not trust Content-Type."""

    @staticmethod
    def _gzip(b: bytes) -> bytes:
        import gzip
        import io as _io
        buf = _io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
            gz.write(b)
        return buf.getvalue()

    def _make_tar_bytes(self, files: dict[str, bytes]) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:") as tar:
            for name, content in files.items():
                info = tarfile.TarInfo(name=name)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
        return buf.getvalue()

    def test_dispatches_to_tar_when_decompressed_body_is_tar(self, tmp_path: Path):
        tar_bytes = self._make_tar_bytes(
            {"paper.tex": b"\\documentclass{amsart}\\begin{document}x\\end{document}"}
        )
        gzipped = self._gzip(tar_bytes)
        kind = _extract_eprint_response(gzipped, tmp_path, "2307.01156")
        assert kind == "tar"
        assert (tmp_path / "paper.tex").exists()

    def test_dispatches_to_tex_when_decompressed_body_is_plain_text(self, tmp_path: Path):
        tex_bytes = b"\\documentclass{amsart}\\begin{document}hello\\end{document}\n"
        gzipped = self._gzip(tex_bytes)
        kind = _extract_eprint_response(gzipped, tmp_path, "2307.01156")
        assert kind == "tex"
        assert (tmp_path / "2307.01156.tex").read_bytes() == tex_bytes

    def test_handles_already_uncompressed_body(self, tmp_path: Path):
        """Tolerate the rare case where the response is not gzip-encoded."""
        tex_bytes = b"\\documentclass{amsart}\\begin{document}hello\\end{document}\n"
        kind = _extract_eprint_response(tex_bytes, tmp_path, "2307.01156")
        assert kind == "tex"
        assert (tmp_path / "2307.01156.tex").read_bytes() == tex_bytes


class TestF5PolitenessContract:
    """F5 — the politeness contract (3-s sleep, 503 backoff with
    Retry-After, User-Agent on every request) must be exercised."""

    def test_503_with_retry_after_sleeps_then_succeeds(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")

        # First call raises 503 with Retry-After=60; second call succeeds.
        sleep_calls: list[float] = []
        monkeypatch.setattr(fetch_seed.time, "sleep", lambda s: sleep_calls.append(s))

        call_count = {"n": 0}

        def fake_fetch_eprint(paper_id, raw_dir, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                err = urllib.error.HTTPError(
                    url="https://export.arxiv.org/e-print/x",
                    code=503,
                    msg="Service Unavailable",
                    hdrs={"Retry-After": "60"},  # type: ignore[arg-type]
                    fp=None,
                )
                raise err
            return FetchResult(
                paper_id=paper_id,
                raw_dir=raw_dir,
                main_tex=None,
                http_status=200,
                bytes_downloaded=1024,
                archive_kind="tar",
            )

        monkeypatch.setattr(fetch_seed, "fetch_eprint", fake_fetch_eprint)

        outcome, result = fetch_with_backoff("2307.01156", tmp_path)
        assert outcome.success is True
        assert result is not None
        # Must have slept at least 60s (the Retry-After value).
        assert any(s >= 60 for s in sleep_calls), f"expected ≥60s sleep, got {sleep_calls}"

    def test_user_agent_on_every_request(self, tmp_path: Path, monkeypatch):
        """fetch_eprint must always pass arXMCP/0.1 (mailto:...) UA."""
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")
        captured_headers: list[dict] = []

        class FakeResp:
            status = 200
            headers = {"Content-Type": "application/x-eprint-tar"}

            def read(self, n=-1):
                # Return a minimal valid gzipped tar.
                tar_bytes = io.BytesIO()
                with tarfile.open(fileobj=tar_bytes, mode="w:gz") as tar:
                    info = tarfile.TarInfo(name="paper.tex")
                    body = b"\\documentclass{amsart}"
                    info.size = len(body)
                    tar.addfile(info, io.BytesIO(body))
                return tar_bytes.getvalue()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return None

        def fake_urlopen(req, *args, **kwargs):
            captured_headers.append(dict(req.header_items()))
            return FakeResp()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        fetch_eprint("2307.01156", tmp_path)
        assert len(captured_headers) == 1
        ua_header = next(
            (v for k, v in captured_headers[0].items() if k.lower() == "user-agent"),
            None,
        )
        assert ua_header is not None
        assert ua_header.startswith("arXMCP/0.1 (mailto:")
        assert "test@example.com" in ua_header
