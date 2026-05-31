"""Unit tests for ``tools._arxiv_api`` (notebook-paper-discovery-m2).

The HTTP layer is mocked via ``monkeypatch.setattr(_arxiv_api, "_fetch_url", …)``
— the ``graph_ingest._fetch_openalex_work`` pattern — so NO live arXiv call
happens in CI. ``tests/test_fetch_seed.py`` continues to exercise the
re-exported names through ``tools.curate_seed`` unchanged.
"""

from __future__ import annotations

import urllib.parse

import pytest

from tools import _arxiv_api
from tools._arxiv_api import (
    Candidate,
    build_query_url,
    fetch_candidates,
    parse_atom_feed,
)


def _search_query(url: str) -> str:
    """Return the decoded ``search_query`` param from a built URL."""
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return qs["search_query"][0]


def _feed(n_entries: int, start_idx: int = 0) -> bytes:
    """Build an Atom feed with ``n_entries`` synthetic math.AG entries."""
    entries = "".join(
        f"<entry>"
        f"<id>http://arxiv.org/abs/2307.{i:05d}v1</id>"
        f"<published>2023-07-04T18:30:00Z</published>"
        f"<summary>abstract number {i}</summary>"
        f"<author><name>A. Author</name></author>"
        f'<arxiv:primary_category term="math.AG"/>'
        f"</entry>"
        for i in range(start_idx, start_idx + n_entries)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom"'
        ' xmlns:arxiv="http://arxiv.org/schemas/atom">'
        f"{entries}</feed>"
    ).encode()


class TestBuildQueryURL:
    def test_no_keywords_matches_legacy_params(self) -> None:
        # Byte-stability guard: with no keywords the URL must carry the same
        # params the pre-m2 build_query_url produced (TestCurateQueryURL).
        url = build_query_url("math.AG", start=0, max_results=200)
        assert "search_query=cat%3Amath.AG" in url
        assert "start=0" in url
        assert "max_results=200" in url
        assert "sortBy=submittedDate" in url
        assert "sortOrder=descending" in url
        assert _search_query(url) == "cat:math.AG"

    def test_positional_start_max_results(self) -> None:
        url = build_query_url("math.AG", 0, 10)
        assert url.startswith("https://export.arxiv.org/api/query?")
        assert "max_results=10" in url

    def test_abs_keywords_compose_quoted_clause(self) -> None:
        url = build_query_url("math.AG", abs_keywords="Bridgeland stability")
        assert _search_query(url) == 'cat:math.AG AND abs:"Bridgeland stability"'

    def test_ti_keywords_compose_quoted_clause(self) -> None:
        url = build_query_url("math.NT", ti_keywords="L-functions")
        assert _search_query(url) == 'cat:math.NT AND ti:"L-functions"'

    def test_both_keyword_clauses(self) -> None:
        url = build_query_url(
            "hep-th", abs_keywords="branes", ti_keywords="mirror symmetry"
        )
        assert _search_query(url) == (
            'cat:hep-th AND abs:"branes" AND ti:"mirror symmetry"'
        )

    def test_keyword_injection_is_contained_in_phrase(self) -> None:
        # FM-3: a hostile keyword cannot inject a bare boolean/field prefix —
        # it stays inside the quoted phrase.
        url = build_query_url("math.AG", abs_keywords="x AND cat:hep-th")
        assert _search_query(url) == 'cat:math.AG AND abs:"x AND cat:hep-th"'

    def test_embedded_quote_is_stripped(self) -> None:
        url = build_query_url("math.AG", abs_keywords='a"b')
        assert _search_query(url) == 'cat:math.AG AND abs:"ab"'

    def test_whitespace_only_keyword_skips_clause(self) -> None:
        # rect F1: a keyword that is blank after stripping quotes+whitespace
        # (e.g. an empty notebook description) must NOT emit a degenerate
        # abs:"" / ti:"" phrase — the clause is dropped entirely.
        assert _search_query(build_query_url("math.AG", abs_keywords="   ")) == "cat:math.AG"
        assert _search_query(build_query_url("math.AG", ti_keywords='""')) == "cat:math.AG"
        # A blank abs but real ti still yields only the ti clause.
        url = build_query_url("math.AG", abs_keywords="  ", ti_keywords="moduli")
        assert _search_query(url) == 'cat:math.AG AND ti:"moduli"'

    def test_empty_category_raises(self) -> None:
        with pytest.raises(ValueError, match="category"):
            build_query_url("")


class TestParseAtomFeed:
    def test_round_trips_entries(self) -> None:
        cands = parse_atom_feed(_feed(2))
        assert [c.paper_id for c in cands] == ["2307.00000", "2307.00001"]
        assert cands[0].submitted_year == 2023
        assert cands[0].n_authors == 1
        assert cands[0].primary_category == "math.AG"

    def test_extracts_title_and_submitted_date(self) -> None:
        # notebook-paper-discovery-m3: <title> + raw <published> are captured.
        feed = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<feed xmlns="http://www.w3.org/2005/Atom"'
            b' xmlns:arxiv="http://arxiv.org/schemas/atom">'
            b"<entry>"
            b"<id>http://arxiv.org/abs/2307.01156v2</id>"
            b"<title>Stability conditions\n  on K3 surfaces</title>"
            b"<published>2023-07-04T18:30:00Z</published>"
            b"<summary>long enough abstract</summary>"
            b"<author><name>A. Author</name></author>"
            b'<arxiv:primary_category term="math.AG"/>'
            b"</entry></feed>"
        )
        c = parse_atom_feed(feed)[0]
        # title is whitespace-collapsed; submitted_date is the raw ISO string.
        assert c.title == "Stability conditions on K3 surfaces"
        assert c.submitted_date == "2023-07-04T18:30:00Z"

    def test_missing_title_defaults_empty(self) -> None:
        # The existing fixture has no <title>; the field defaults to "".
        c = parse_atom_feed(_feed(1))[0]
        assert c.title == ""
        assert c.submitted_date == "2023-07-04T18:30:00Z"

    def test_error_entry_raises(self) -> None:
        # FM-6: arXiv signals errors as HTTP-200 with an /api/errors# id.
        feed = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<feed xmlns="http://www.w3.org/2005/Atom"'
            b' xmlns:arxiv="http://arxiv.org/schemas/atom">'
            b"<entry>"
            b"<id>http://arxiv.org/api/errors#incorrect_query</id>"
            b"<summary>incorrect or malformed query</summary>"
            b"</entry></feed>"
        )
        with pytest.raises(RuntimeError, match="error entry"):
            parse_atom_feed(feed)

    def test_non_xml_response_raises_runtimeerror(self) -> None:
        # rect m4-F1: arXiv can return an HTML maintenance/redirect page; the
        # defusedxml ParseError (a SyntaxError subclass) is converted to
        # RuntimeError so callers' RuntimeError handlers catch it (no 500).
        with pytest.raises(RuntimeError, match="non-XML"):
            # Unclosed/garbage bytes (e.g. a truncated response) -> ParseError.
            parse_atom_feed(b"<html><body>503 Service Unavailable")


class TestFetchCandidates:
    def test_single_page_no_sleep(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        sleeps: list[float] = []
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url",
            lambda url, contact_email=None: (calls.append(url), _feed(200))[1],
        )
        out = fetch_candidates("math.AG", 200, sleep=sleeps.append)
        assert len(out) == 200
        assert len(calls) == 1  # one request for max_results <= page size
        assert sleeps == []  # no inter-page sleep on the single-page path

    def test_multi_page_sleeps_between_pages(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[str] = []
        sleeps: list[float] = []
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url",
            lambda url, contact_email=None: (calls.append(url), _feed(2000))[1],
        )
        out = fetch_candidates("math.AG", 5000, sleep=sleeps.append)
        assert len(out) == 5000  # truncated to max_results
        assert len(calls) == 3  # 2000 + 2000 + 2000 -> 6000, truncated
        assert sleeps == [_arxiv_api.POLITENESS_SLEEP_SECONDS] * 2

    def test_empty_page_terminates(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pages = [_feed(2000), _feed(0)]
        sleeps: list[float] = []

        def _stub(url: str, contact_email: str | None = None) -> bytes:
            return pages.pop(0)

        monkeypatch.setattr(_arxiv_api, "_fetch_url", _stub)
        out = fetch_candidates("math.AG", 5000, sleep=sleeps.append)
        assert len(out) == 2000
        assert len(sleeps) == 1

    def test_short_page_terminates(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # A page shorter than page_size means the feed is exhausted -> stop.
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url",
            lambda url, contact_email=None: _feed(120),
        )
        out = fetch_candidates("math.AG", 5000, sleep=lambda _s: None)
        assert len(out) == 120

    def test_non_positive_max_results_raises(self) -> None:
        with pytest.raises(ValueError, match="max_results"):
            fetch_candidates("math.AG", 0)


class TestReExport:
    def test_curate_seed_reexports_resolve(self) -> None:
        from tools.curate_seed import (
            Candidate as CSCandidate,
        )
        from tools.curate_seed import (
            build_query_url as cs_build,
        )
        from tools.curate_seed import (
            fetch_candidates as cs_fetch,
        )
        from tools.curate_seed import (
            parse_atom_feed as cs_parse,
        )

        assert CSCandidate is Candidate
        assert cs_build is build_query_url
        assert cs_fetch is fetch_candidates
        assert cs_parse is parse_atom_feed
        # The dataclass still constructs identically.
        c = CSCandidate(
            paper_id="2307.01156", submitted_year=2023, n_authors=2,
            primary_category="math.AG", abstract_head="x" * 200,
        )
        assert c.as_tsv_row().split("\t")[0] == "2307.01156"
