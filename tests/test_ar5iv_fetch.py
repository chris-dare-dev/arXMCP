"""Tests for the ar5iv cache fetcher (E11_S01).

Covers the happy path (200 + math → hit), the miss paths (404,
timeout, error banner without `<math>`), and the on-disk cache
short-circuit. All tests mock `urllib.request.urlopen` so the
suite runs offline.
"""

from __future__ import annotations

import io
import urllib.error
from unittest.mock import patch

import pytest

from ingest.ar5iv_fetch import (
    Ar5ivResult,
    try_cache,
)


class _FakeResponse:
    """Minimal stub for the urllib response context manager.

    E13_S07: ``headers`` attribute provided so the new Content-Length
    pre-check in ``ar5iv_fetch.try_cache`` can inspect the response.
    Default ``content_length=None`` omits the header (the fetcher
    treats absence as "fall back to read-cap"). Pass an int to
    inject a declared size; values above
    ``AR5IV_MAX_RESPONSE_BYTES`` exercise the early-reject branch.
    """

    def __init__(
        self,
        status: int,
        body: bytes,
        url: str | None = None,
        *,
        content_length: int | None = None,
    ):
        self.status = status
        self._body = body
        # F9 regression: ``response.url`` is what urllib reports as
        # the *final* URL after any redirects. Default to the ar5iv
        # base so existing tests stay green.
        self.url = url if url is not None else (
            "https://ar5iv.labs.arxiv.org/html/test"
        )
        if content_length is None:
            self.headers: dict[str, str] = {}
        else:
            self.headers = {"Content-Length": str(content_length)}

    def read(self, amt: int | None = None) -> bytes:
        # E13_S07 contract: production code passes
        # ``AR5IV_MAX_RESPONSE_BYTES + 1`` to bound memory. We honor
        # the cap so existing small-body tests pass unchanged.
        if amt is None:
            return self._body
        return self._body[:amt]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _ok_response(body: str = '<html><math display="block"/></html>') -> _FakeResponse:
    return _FakeResponse(200, body.encode("utf-8"))


class TestTryCache:
    def test_happy_path_writes_both_files(self, tmp_path):
        cache_dir = tmp_path / "cache"
        parsed_dir = tmp_path / "parsed"
        with patch(
            "ingest.ar5iv_fetch.urllib.request.urlopen",
            return_value=_ok_response(),
        ):
            result = try_cache(
                "2401.00001",
                cache_dir=cache_dir,
                parsed_dir=parsed_dir,
            )
        assert result.hit is True
        assert result.reason == "ok"
        assert result.cache_path == cache_dir / "2401.00001.html"
        assert result.parsed_path == parsed_dir / "2401.00001" / "index.html"
        assert result.cache_path.is_file()
        assert result.parsed_path.is_file()
        # Body is exactly what urllib returned.
        assert "<math" in result.cache_path.read_text()

    def test_local_cache_short_circuits_network(self, tmp_path):
        cache_dir = tmp_path / "cache"
        parsed_dir = tmp_path / "parsed"
        # Pre-populate both files.
        (cache_dir).mkdir(parents=True)
        (parsed_dir / "2401.00001").mkdir(parents=True)
        (cache_dir / "2401.00001.html").write_text("<html/>")
        (parsed_dir / "2401.00001" / "index.html").write_text("<html/>")
        # urlopen should NOT be called.
        with patch(
            "ingest.ar5iv_fetch.urllib.request.urlopen",
            side_effect=AssertionError("network must not be hit"),
        ):
            result = try_cache(
                "2401.00001",
                cache_dir=cache_dir,
                parsed_dir=parsed_dir,
            )
        assert result.hit is True
        assert result.reason == "ok_local_cache"

    def test_404_returns_miss(self, tmp_path):
        cache_dir = tmp_path / "cache"
        parsed_dir = tmp_path / "parsed"
        with patch(
            "ingest.ar5iv_fetch.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                url="x", code=404, msg="Not Found", hdrs=None,
                fp=io.BytesIO(b""),
            ),
        ):
            result = try_cache(
                "2401.00001",
                cache_dir=cache_dir,
                parsed_dir=parsed_dir,
            )
        assert result.hit is False
        assert result.reason == "http_404"
        # No files written on miss.
        assert not (cache_dir / "2401.00001.html").exists()

    def test_timeout_returns_miss(self, tmp_path):
        cache_dir = tmp_path / "cache"
        parsed_dir = tmp_path / "parsed"
        with patch(
            "ingest.ar5iv_fetch.urllib.request.urlopen",
            side_effect=TimeoutError("timed out"),
        ):
            result = try_cache(
                "2401.00001",
                cache_dir=cache_dir,
                parsed_dir=parsed_dir,
            )
        assert result.hit is False
        assert result.reason == "timeout_or_network"

    def test_200_with_no_math_treated_as_miss(self, tmp_path):
        """ar5iv error banner returns 200 with no <math element."""
        cache_dir = tmp_path / "cache"
        parsed_dir = tmp_path / "parsed"
        body = "<html><body>this paper could not be processed</body></html>"
        with patch(
            "ingest.ar5iv_fetch.urllib.request.urlopen",
            return_value=_FakeResponse(200, body.encode()),
        ):
            result = try_cache(
                "2401.00001",
                cache_dir=cache_dir,
                parsed_dir=parsed_dir,
            )
        assert result.hit is False
        assert result.reason == "no_math_in_body"
        assert not (cache_dir / "2401.00001.html").exists()

    def test_rejects_malformed_paper_id(self, tmp_path):
        with pytest.raises(ValueError, match="paper_id"):
            try_cache(
                "../../../etc",
                cache_dir=tmp_path / "cache",
                parsed_dir=tmp_path / "parsed",
            )

    def test_word_boundary_rejects_css_class_math_substring(self, tmp_path):
        """Closes F4: ``<math.foo`` is not the same as a ``<math>`` open
        tag. The body-content guard uses ``<math\\b`` so substrings
        embedded in CSS class names (e.g. ``<math-error>``) do not
        false-positive into a "hit"."""
        cache_dir = tmp_path / "cache"
        parsed_dir = tmp_path / "parsed"
        # Body has the substring ``<math`` ONLY inside a hyphenated
        # tag name. No actual MathML.
        body = (
            "<html><body><math-error/>"
            "this paper could not be processed</body></html>"
        )
        with patch(
            "ingest.ar5iv_fetch.urllib.request.urlopen",
            return_value=_FakeResponse(200, body.encode()),
        ):
            result = try_cache(
                "2401.00001",
                cache_dir=cache_dir,
                parsed_dir=parsed_dir,
            )
        assert result.hit is False
        assert result.reason == "no_math_in_body"

    def test_error_banner_with_math_tag_still_rejected(self, tmp_path):
        """Closes F4 (belt-and-braces): if ar5iv ever serves the error
        banner AND a stray ``<math>`` element on the same page, the
        belt-and-braces banner check rejects the response."""
        cache_dir = tmp_path / "cache"
        parsed_dir = tmp_path / "parsed"
        body = (
            "<html><body>this paper could not be processed"
            "<math display='block'/></body></html>"
        )
        with patch(
            "ingest.ar5iv_fetch.urllib.request.urlopen",
            return_value=_FakeResponse(200, body.encode()),
        ):
            result = try_cache(
                "2401.00001",
                cache_dir=cache_dir,
                parsed_dir=parsed_dir,
            )
        assert result.hit is False
        assert result.reason == "no_math_in_body"

    def test_offdomain_redirect_treated_as_miss(self, tmp_path):
        """Closes F9: a 3xx response whose final URL lives off
        ``ar5iv.labs.arxiv.org`` is treated as a miss rather than a
        hit. urllib silently follows redirects; we re-validate the
        final URL before trusting the body."""
        cache_dir = tmp_path / "cache"
        parsed_dir = tmp_path / "parsed"
        attacker_body = (
            "<html><math display='block'>evil</math></html>"
        )
        with patch(
            "ingest.ar5iv_fetch.urllib.request.urlopen",
            return_value=_FakeResponse(
                200, attacker_body.encode(), url="https://evil.example/x"
            ),
        ):
            result = try_cache(
                "2401.00001",
                cache_dir=cache_dir,
                parsed_dir=parsed_dir,
            )
        assert result.hit is False
        assert result.reason == "unexpected_redirect"
        assert not (cache_dir / "2401.00001.html").exists()

    def test_result_dataclass_is_frozen(self, tmp_path):
        # Mostly a smoke test that the dataclass shape compiles.
        r = Ar5ivResult(
            paper_id="x",
            hit=False,
            cache_path=None,
            parsed_path=None,
            reason="test",
        )
        with pytest.raises((AttributeError, Exception)):
            r.hit = True  # frozen
