"""arxiv.org/html native-HTML ingestion closure (stage2/arx-a45 — AC-A.16).

Covers the four halves of the WS-A A4 ingestion milestone:

1. URL-paste acceptance: ``https://arxiv.org/html/<id>`` validates in
   ``server.routes.notebooks._arxiv_url_to_paper_id`` alongside the
   existing ``/abs/`` and ar5iv forms.
2. Fetch ladder: native → ar5iv → local LaTeXML, unit-tested with
   mocked failures at each rung (``try_native`` / ``try_cache`` /
   on-disk parsed HTML) through both ``try_html_sources`` and
   ``ingest.bulk_ingest.ingest_one_paper``.
3. Golden-fixture chunker regression: one committed native-HTML page
   (``tests/fixtures/native_html/2603.90001/`` — synthetic,
   license-safe, modeled on the live-verified native markup shape
   from finding 211 R-E) passes through the chunker producing
   theorem/section/proof structure equal to its recorded baseline.
4. LaTeXML generator-version drift tripwire: extraction from both
   render families' comment shape + per-ingest JSONL persistence.

Offline throughout: HTTP is mocked at ``urllib.request.urlopen`` or at
the rung boundary (house convention from ``tests/test_ar5iv_fetch.py``).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest

from ingest.ar5iv_fetch import (
    ARXIV_NATIVE_BASE_URL,
    Ar5ivResult,
    extract_latexml_generator,
    try_html_sources,
    try_native,
)
from server.routes.notebooks import _arxiv_url_to_paper_id

# ---------------------------------------------------------------------------
# Shared stubs (house convention: tests/test_ar5iv_fetch.py)
# ---------------------------------------------------------------------------

_GENERATOR_COMMENT = (
    "<!-- Generated on Sat Jun 27 03:14:15 2026 by LaTeXML "
    "(version 0.8.8) http://dlmf.nist.gov/LaTeXML/. -->"
)


class _FakeResponse:
    def __init__(self, status: int, body: bytes, url: str | None = None):
        self.status = status
        self._body = body
        self.url = url if url is not None else (
            f"{ARXIV_NATIVE_BASE_URL}/2603.90001v1"
        )
        self.headers: dict[str, str] = {}

    def read(self, amt: int | None = None) -> bytes:
        return self._body if amt is None else self._body[:amt]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _native_body() -> bytes:
    return (
        f"<html>{_GENERATOR_COMMENT}"
        f'<math class="ltx_Math" alttext="x"/></html>'
    ).encode()


def _miss(paper_id: str, reason: str, source: str) -> Ar5ivResult:
    return Ar5ivResult(
        paper_id=paper_id,
        hit=False,
        cache_path=None,
        parsed_path=None,
        reason=reason,
        source=source,
    )


def _hit(paper_id: str, source: str, tmp_path: Path) -> Ar5ivResult:
    return Ar5ivResult(
        paper_id=paper_id,
        hit=True,
        cache_path=tmp_path / f"{paper_id}.html",
        parsed_path=tmp_path / paper_id / "index.html",
        reason="ok",
        source=source,
        latexml_generator="0.8.8",
    )


# ---------------------------------------------------------------------------
# 1. URL-paste acceptance (server/routes/notebooks.py)
# ---------------------------------------------------------------------------


class TestNativeUrlAcceptance:
    """AC-A.16 first clause: pasting ``https://arxiv.org/html/<id>``
    into add-paper succeeds at the URL-validation boundary."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://arxiv.org/html/2603.23033", "2603.23033"),
            ("https://arxiv.org/html/2603.23033v1", "2603.23033v1"),
            ("http://arxiv.org/html/2603.23033", "2603.23033"),
            ("https://arxiv.org/html/2603.23033/", "2603.23033"),
            ("https://arxiv.org/html/hep-th/0001234", "hep-th/0001234"),
            # The pre-existing forms must keep working unchanged.
            ("https://arxiv.org/abs/2603.23033", "2603.23033"),
            ("https://ar5iv.labs.arxiv.org/html/2603.23033", "2603.23033"),
        ],
    )
    def test_accepted(self, url: str, expected: str):
        assert _arxiv_url_to_paper_id(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            # Negative tests per the acceptance-criteria seed:
            # malformed arxiv.org/html URLs are still rejected.
            "https://arxiv.org/html/",
            "https://arxiv.org/html/not-a-paper-id",
            "https://arxiv.org/html/2603.23033/../../etc/passwd",
            "https://arxiv.org/pdf/2603.23033",
            "https://arxiv.org/htmlx/2603.23033",
            "https://ar5iv.labs.arxiv.org/abs/2603.23033",
            "https://www.arxiv.org/html/2603.23033",
            "https://evil.example/html/2603.23033",
            "ftp://arxiv.org/html/2603.23033",
        ],
    )
    def test_rejected(self, url: str):
        assert _arxiv_url_to_paper_id(url) is None


# ---------------------------------------------------------------------------
# 2a. try_native — the new first rung
# ---------------------------------------------------------------------------


class TestTryNative:
    def test_happy_path_writes_cache_and_parsed(self, tmp_path):
        cache_dir = tmp_path / "native-cache"
        parsed_dir = tmp_path / "parsed"
        with patch(
            "ingest.ar5iv_fetch.urllib.request.urlopen",
            return_value=_FakeResponse(200, _native_body()),
        ) as urlopen_mock:
            result = try_native(
                "2603.90001", cache_dir=cache_dir, parsed_dir=parsed_dir,
            )
        assert result.hit
        assert result.source == "native_html"
        assert result.reason == "ok"
        assert result.latexml_generator == "0.8.8"
        assert (cache_dir / "2603.90001.html").is_file()
        assert (parsed_dir / "2603.90001" / "index.html").is_file()
        requested = urlopen_mock.call_args[0][0].full_url
        assert requested == f"{ARXIV_NATIVE_BASE_URL}/2603.90001"

    def test_versioned_redirect_within_base_is_accepted(self, tmp_path):
        # arXiv redirects /html/<id> to /html/<id>v<N>; that stays
        # under the pinned base URL and must NOT trip the F9 guard.
        with patch(
            "ingest.ar5iv_fetch.urllib.request.urlopen",
            return_value=_FakeResponse(
                200, _native_body(),
                url=f"{ARXIV_NATIVE_BASE_URL}/2603.90001v2",
            ),
        ):
            result = try_native(
                "2603.90001",
                cache_dir=tmp_path / "c",
                parsed_dir=tmp_path / "p",
            )
        assert result.hit

    def test_off_base_redirect_rejected(self, tmp_path):
        with patch(
            "ingest.ar5iv_fetch.urllib.request.urlopen",
            return_value=_FakeResponse(
                200, _native_body(), url="https://evil.example/2603.90001",
            ),
        ):
            result = try_native(
                "2603.90001",
                cache_dir=tmp_path / "c",
                parsed_dir=tmp_path / "p",
            )
        assert not result.hit
        assert result.reason == "unexpected_redirect"

    def test_404_maps_to_miss(self, tmp_path):
        import urllib.error

        with patch(
            "ingest.ar5iv_fetch.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                "https://arxiv.org/html/2603.90001", 404, "nf", {}, None,
            ),
        ):
            result = try_native(
                "2603.90001",
                cache_dir=tmp_path / "c",
                parsed_dir=tmp_path / "p",
            )
        assert not result.hit
        assert result.reason == "http_404"
        assert result.source == "native_html"

    def test_malformed_paper_id_raises(self, tmp_path):
        with pytest.raises(ValueError, match="does not match"):
            try_native(
                "../../etc/passwd",
                cache_dir=tmp_path / "c",
                parsed_dir=tmp_path / "p",
            )


# ---------------------------------------------------------------------------
# 2b. try_html_sources — ladder order with mocked failures
# ---------------------------------------------------------------------------


class TestLadderOrder:
    """AC-A.16: the fetch ladder tries native HTML → ar5iv → local
    LaTeXML in that order (the third rung is the caller's, exercised
    in TestBulkIngestLadder below)."""

    def test_native_hit_short_circuits_ar5iv(self, tmp_path):
        calls: list[str] = []

        def _native(paper_id, **kw):
            calls.append("native")
            return _hit(paper_id, "native_html", tmp_path)

        def _ar5iv(paper_id, **kw):
            calls.append("ar5iv")
            return _miss(paper_id, "http_404", "ar5iv")

        with (
            patch("ingest.ar5iv_fetch.try_native", side_effect=_native),
            patch("ingest.ar5iv_fetch.try_cache", side_effect=_ar5iv),
        ):
            result = try_html_sources(
                "2603.90001",
                native_cache_dir=tmp_path / "n",
                ar5iv_cache_dir=tmp_path / "a",
                parsed_dir=tmp_path / "p",
            )
        assert result.hit
        assert result.source == "native_html"
        assert calls == ["native"]

    def test_native_miss_falls_to_ar5iv(self, tmp_path):
        calls: list[str] = []

        def _native(paper_id, **kw):
            calls.append("native")
            return _miss(paper_id, "http_404", "native_html")

        def _ar5iv(paper_id, **kw):
            calls.append("ar5iv")
            return _hit(paper_id, "ar5iv", tmp_path)

        with (
            patch("ingest.ar5iv_fetch.try_native", side_effect=_native),
            patch("ingest.ar5iv_fetch.try_cache", side_effect=_ar5iv),
        ):
            result = try_html_sources(
                "2603.90001",
                native_cache_dir=tmp_path / "n",
                ar5iv_cache_dir=tmp_path / "a",
                parsed_dir=tmp_path / "p",
            )
        assert result.hit
        assert result.source == "ar5iv"
        assert calls == ["native", "ar5iv"]

    def test_double_miss_returns_ar5iv_reason(self, tmp_path):
        with (
            patch(
                "ingest.ar5iv_fetch.try_native",
                return_value=_miss("2603.90001", "http_404", "native_html"),
            ),
            patch(
                "ingest.ar5iv_fetch.try_cache",
                return_value=_miss("2603.90001", "http_429", "ar5iv"),
            ),
        ):
            result = try_html_sources(
                "2603.90001",
                native_cache_dir=tmp_path / "n",
                ar5iv_cache_dir=tmp_path / "a",
                parsed_dir=tmp_path / "p",
            )
        assert not result.hit
        assert result.reason == "http_429"

    def test_prior_ar5iv_cache_short_circuits_without_network(self, tmp_path):
        # A paper fetched via ar5iv BEFORE the native rung existed
        # must keep short-circuiting locally — zero network calls.
        ar5iv_cache = tmp_path / "a"
        parsed_dir = tmp_path / "p"
        ar5iv_cache.mkdir()
        (parsed_dir / "2603.90001").mkdir(parents=True)
        (ar5iv_cache / "2603.90001.html").write_text(
            f"{_GENERATOR_COMMENT}<math/>", encoding="utf-8",
        )
        (parsed_dir / "2603.90001" / "index.html").write_text(
            "<math/>", encoding="utf-8",
        )
        with patch(
            "ingest.ar5iv_fetch.urllib.request.urlopen",
            side_effect=AssertionError("no network call allowed"),
        ):
            result = try_html_sources(
                "2603.90001",
                native_cache_dir=tmp_path / "n",
                ar5iv_cache_dir=ar5iv_cache,
                parsed_dir=parsed_dir,
            )
        assert result.hit
        assert result.reason == "ok_local_cache"
        assert result.source == "ar5iv"
        assert result.latexml_generator == "0.8.8"

    def test_malformed_paper_id_raises(self, tmp_path):
        with pytest.raises(ValueError, match="does not match"):
            try_html_sources(
                "not a paper id",
                native_cache_dir=tmp_path / "n",
                ar5iv_cache_dir=tmp_path / "a",
                parsed_dir=tmp_path / "p",
            )


# ---------------------------------------------------------------------------
# 2c. bulk_ingest ladder — native → ar5iv → local LaTeXML
# ---------------------------------------------------------------------------


class TestBulkIngestLadder:
    def _native_miss(self, paper_id="2401.00001"):
        return _miss(paper_id, "http_404", "native_html")

    def test_native_hit_selected_first(self, tmp_path):
        from ingest.bulk_ingest import ingest_one_paper

        parsed_dir = tmp_path / "parsed"
        (parsed_dir / "2401.00001").mkdir(parents=True)
        (parsed_dir / "2401.00001" / "index.html").write_text("<html/>")

        with (
            patch(
                "ingest.bulk_ingest.try_native",
                return_value=Ar5ivResult(
                    paper_id="2401.00001",
                    hit=True,
                    cache_path=tmp_path / "n" / "2401.00001.html",
                    parsed_path=parsed_dir / "2401.00001" / "index.html",
                    reason="ok",
                    source="native_html",
                    latexml_generator="0.8.8",
                ),
            ),
            patch(
                "ingest.bulk_ingest.try_cache",
                side_effect=AssertionError(
                    "ar5iv rung must not fire after a native hit"
                ),
            ),
            patch("ingest.bulk_ingest.chunk_paper", return_value=[]),
        ):
            outcome = ingest_one_paper(
                "2401.00001",
                lancedb_staging_path=tmp_path / "staging",
                ar5iv_cache_dir=tmp_path / "a",
                native_cache_dir=tmp_path / "n",
                parsed_dir=parsed_dir,
            )
        assert outcome.parser_used == "native_html"
        assert outcome.latexml_generator == "0.8.8"
        assert outcome.parsers_tried == ["native_html"]

    def test_native_miss_falls_to_ar5iv_then_latexml(self, tmp_path):
        from ingest.bulk_ingest import ingest_one_paper

        parsed_dir = tmp_path / "parsed"
        paper_dir = parsed_dir / "2401.00001"
        paper_dir.mkdir(parents=True)
        (paper_dir / "index.html").write_text(
            f"{_GENERATOR_COMMENT}<html/>", encoding="utf-8",
        )

        with (
            patch(
                "ingest.bulk_ingest.try_native",
                return_value=self._native_miss(),
            ),
            patch(
                "ingest.bulk_ingest.try_cache",
                return_value=_miss("2401.00001", "http_404", "ar5iv"),
            ),
            patch("ingest.bulk_ingest.chunk_paper", return_value=[]),
        ):
            outcome = ingest_one_paper(
                "2401.00001",
                lancedb_staging_path=tmp_path / "staging",
                ar5iv_cache_dir=tmp_path / "a",
                native_cache_dir=tmp_path / "n",
                parsed_dir=parsed_dir,
            )
        # Third rung: pre-parsed local LaTeXML HTML.
        assert outcome.parser_used == "latexml"
        assert outcome.parsers_tried == ["native_html", "ar5iv", "latexml"]
        # Drift tripwire fires on the local rung too.
        assert outcome.latexml_generator == "0.8.8"

    def test_existing_ar5iv_cache_skips_native_network(self, tmp_path):
        """A paper already served by a prior ar5iv fetch must not
        trigger a native network attempt (wasted egress)."""
        from ingest.bulk_ingest import ingest_one_paper

        parsed_dir = tmp_path / "parsed"
        ar5iv_cache = tmp_path / "a"
        (parsed_dir / "2401.00001").mkdir(parents=True)
        (parsed_dir / "2401.00001" / "index.html").write_text("<html/>")
        ar5iv_cache.mkdir()
        (ar5iv_cache / "2401.00001.html").write_text("<html/>")

        with (
            patch(
                "ingest.bulk_ingest.try_native",
                side_effect=AssertionError(
                    "native rung must not fire for an ar5iv-cached paper"
                ),
            ),
            patch("ingest.bulk_ingest.chunk_paper", return_value=[]),
        ):
            outcome = ingest_one_paper(
                "2401.00001",
                lancedb_staging_path=tmp_path / "staging",
                ar5iv_cache_dir=ar5iv_cache,
                native_cache_dir=tmp_path / "n",
                parsed_dir=parsed_dir,
            )
        assert outcome.parser_used == "ar5iv"


# ---------------------------------------------------------------------------
# 3. Golden-fixture chunker regression (the committed baseline)
# ---------------------------------------------------------------------------

_NATIVE_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "native_html"
_NATIVE_PAPER_ID = "2603.90001"


def _load_native_expected() -> dict:
    return json.loads(
        (_NATIVE_FIXTURE_DIR / f"{_NATIVE_PAPER_ID}.expected.json").read_text(
            encoding="utf-8"
        )
    )


def _chunk_native_fixture(tmp_path: Path):
    from ingest.chunker import chunk_paper

    parsed_dir = tmp_path / "parsed"
    chunks_dir = tmp_path / "chunks"
    paper_parsed = parsed_dir / _NATIVE_PAPER_ID
    paper_parsed.mkdir(parents=True)
    (paper_parsed / "index.html").write_bytes(
        (_NATIVE_FIXTURE_DIR / _NATIVE_PAPER_ID / "index.html").read_bytes()
    )
    with (
        patch("ingest.chunker.PARSED_DIR", parsed_dir),
        patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
    ):
        return chunk_paper(_NATIVE_PAPER_ID)


class TestNativeHtmlGoldenFixture:
    """AC-A.16 golden fixture: a native-HTML page passes through the
    chunker producing chunks with theorem/section/proof structure
    equal to its recorded baseline (regeneration procedure:
    ``.claude/docs/chunker-fixtures.md`` — same bootstrap as the
    E02_S05 suite)."""

    def test_chunk_count_matches_baseline(self, tmp_path):
        expected = _load_native_expected()
        chunks = _chunk_native_fixture(tmp_path)
        assert len(chunks) == expected["chunk_count"]

    def test_kind_counts_match_baseline(self, tmp_path):
        expected = _load_native_expected()
        chunks = _chunk_native_fixture(tmp_path)
        actual = dict(Counter(c.kind for c in chunks))
        assert actual == expected["kind_counts"]

    def test_chunk_ids_match_baseline_in_document_order(self, tmp_path):
        expected = _load_native_expected()
        chunks = _chunk_native_fixture(tmp_path)
        assert [c.chunk_id for c in chunks] == expected["expected_chunk_ids"]

    def test_theorem_proof_pairing_survives_native_class_suffixes(
        self, tmp_path
    ):
        # Native renders carry per-author environment suffixes
        # (ltx_theorem_theo/lemm/defi — finding 211 R-E table). The
        # chunker's suffix-agnostic regex must pair each proof with
        # its preceding theorem-family sibling.
        chunks = _chunk_native_fixture(tmp_path)
        proofs = [c for c in chunks if c.kind == "proof"]
        assert len(proofs) == 2
        stmts = [c for c in chunks if c.kind == "stmt"]
        assert len(stmts) == 3

    def test_math_alttext_roundtrip_and_chrome_invisible(self, tmp_path):
        chunks = _chunk_native_fixture(tmp_path)
        all_body = " ".join(c.body_text for c in chunks)
        # F1 math-fidelity: alttext LaTeX lands in body_text as $TeX$.
        assert r"$\mathcal{A}$" in all_body
        assert r"$Z:K(\mathcal{A})\to\mathbb{C}$" in all_body
        # arXiv site chrome and MathML `intent` accessibility
        # attributes must be invisible to chunk bodies.
        assert "static/browse" not in all_body
        assert "intent" not in all_body
        assert ":literal" not in all_body

    def test_fixture_generator_comment_extractable(self):
        # The fixture carries the native generator comment; the drift
        # tripwire must read it (ties fixture + tripwire together).
        html = (
            _NATIVE_FIXTURE_DIR / _NATIVE_PAPER_ID / "index.html"
        ).read_text(encoding="utf-8")
        assert extract_latexml_generator(html) == "0.8.8"


# ---------------------------------------------------------------------------
# 4. Generator-version drift tripwire
# ---------------------------------------------------------------------------


class TestGeneratorVersionTripwire:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            # ar5iv comment shape (observed in cache/ar5iv/*.html).
            (
                "<!--Generated on Tue Mar 12 05:45:28 2024 by LaTeXML "
                "(version 0.8.8) http://dlmf.nist.gov/LaTeXML/.-->",
                "0.8.8",
            ),
            # native comment shape (space after <!--).
            (_GENERATOR_COMMENT, "0.8.8"),
            # future-version tolerance.
            ("by LaTeXML (version 0.9.1-rust)", "0.9.1-rust"),
            ("<html>no comment here</html>", None),
            ("", None),
        ],
    )
    def test_extract(self, text: str, expected: str | None):
        assert extract_latexml_generator(text) == expected

    def test_bulk_ingest_persists_generator_jsonl(self, tmp_path):
        """AC-A.16 last clause: the LaTeXML generator-version string
        is persisted per ingest (ops JSONL beside ingestion.log)."""
        from ingest.bulk_ingest import run_bulk_ingest

        parsed_dir = tmp_path / "parsed"
        paper_dir = parsed_dir / "2401.00001"
        paper_dir.mkdir(parents=True)
        (paper_dir / "index.html").write_text(
            f"{_GENERATOR_COMMENT}<html/>", encoding="utf-8",
        )
        log_path = tmp_path / "ops" / "ingestion.log"

        with (
            patch(
                "ingest.bulk_ingest.try_native",
                return_value=self._miss_native(),
            ),
            patch(
                "ingest.bulk_ingest.try_cache",
                return_value=_miss("2401.00001", "http_404", "ar5iv"),
            ),
            # Chunker returns empty → paper counted failed, but the
            # parser DID run (latexml rung) so the generator record
            # must still be appended.
            patch("ingest.bulk_ingest.chunk_paper", return_value=[]),
        ):
            run_bulk_ingest(
                ["2401.00001"],
                lancedb_staging_path=tmp_path / "staging",
                ar5iv_cache_dir=tmp_path / "a",
                native_cache_dir=tmp_path / "n",
                parsed_dir=parsed_dir,
                failures_path=tmp_path / "ops" / "failures.jsonl",
                log_path=log_path,
                ops_dir=tmp_path / "ops",
            )

        generators_path = log_path.parent / "latexml-generators.jsonl"
        assert generators_path.is_file()
        records = [
            json.loads(line)
            for line in generators_path.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        assert len(records) == 1
        assert records[0]["paper_id"] == "2401.00001"
        assert records[0]["parser"] == "latexml"
        assert records[0]["generator"] == "0.8.8"
        assert "timestamp" in records[0]

    @staticmethod
    def _miss_native():
        return _miss("2401.00001", "http_404", "native_html")
