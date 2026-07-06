"""Tests for the paper-metadata-m1 additions to ``tools._arxiv_api``.

Covers the t-atom-mapper acceptance (old-style Atom entry → record
with title/authors/abstract/year/categories; ``math/0212237v1`` →
``math/0212237`` with the archive prefix intact) and the id_list URL
builder guards (``max_results`` ≥ ``len(id_list)`` — the arXiv
default of 10 silently truncates batches). All offline: synthetic
Atom bytes only, no network.

The legacy ``parse_atom_feed`` / ``Candidate`` surface is byte-locked
for ``curate_seed`` + discovery; ``TestLegacyCandidateStability`` pins
that the m1 additions did NOT change its (prefix-dropping) behaviour.
"""

from __future__ import annotations

import urllib.parse

import pytest

from tools._arxiv_api import (
    MAX_RESULTS_PER_PAGE,
    build_id_list_url,
    extract_paper_id_from_abs_url,
    parse_atom_feed,
    parse_atom_metadata,
    strip_id_version,
)


def _entry(
    id_url: str,
    *,
    title: str = "Stability conditions on triangulated categories",
    authors: tuple[str, ...] = ("Tom Bridgeland",),
    summary: str = "We introduce the notion of a stability condition.",
    published: str = "2002-12-18T00:00:00Z",
    categories: tuple[str, ...] = ("math.AG", "math.CT"),
    primary: str = "math.AG",
) -> str:
    author_xml = "".join(f"<author><name>{a}</name></author>" for a in authors)
    cat_xml = "".join(f'<category term="{c}"/>' for c in categories)
    return (
        f"<entry>"
        f"<id>{id_url}</id>"
        f"<title>{title}</title>"
        f"<published>{published}</published>"
        f"<summary>{summary}</summary>"
        f"{author_xml}"
        f"{cat_xml}"
        f'<arxiv:primary_category term="{primary}"/>'
        f"</entry>"
    )


def _feed(*entries: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom"'
        ' xmlns:arxiv="http://arxiv.org/schemas/atom">'
        f"{''.join(entries)}</feed>"
    ).encode()


def _query_params(url: str) -> dict[str, str]:
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return {k: v[0] for k, v in qs.items()}


class TestStripAndExtract:
    def test_strip_id_version(self) -> None:
        assert strip_id_version("math/0212237v1") == "math/0212237"
        assert strip_id_version("2307.01156v12") == "2307.01156"
        assert strip_id_version("math/0212237") == "math/0212237"
        assert strip_id_version("2307.01156") == "2307.01156"

    def test_extract_preserves_old_style_prefix(self) -> None:
        assert (
            extract_paper_id_from_abs_url("http://arxiv.org/abs/math/0212237v1")
            == "math/0212237"
        )
        assert (
            extract_paper_id_from_abs_url("http://arxiv.org/abs/alg-geom/9410026")
            == "alg-geom/9410026"
        )

    def test_extract_new_style_strips_version(self) -> None:
        assert (
            extract_paper_id_from_abs_url("http://arxiv.org/abs/2307.01156v2")
            == "2307.01156"
        )

    def test_extract_without_abs_marker_degrades_to_last_segment(self) -> None:
        # Unrecognized URL shapes degrade (caller correlates against
        # requested ids, so this surfaces as a per-id miss, not a crash).
        assert extract_paper_id_from_abs_url("http://example.org/x/0212237v1") == (
            "0212237"
        )


class TestBuildIdListURL:
    def test_max_results_defaults_to_id_count(self) -> None:
        ids = ["math/0212237", "0708.2247", "2303.07061"]
        params = _query_params(build_id_list_url(ids))
        # The arXiv default (10) silently truncates id_list batches;
        # the builder MUST pin max_results >= len(id_list).
        assert int(params["max_results"]) == len(ids)
        assert params["start"] == "0"
        assert params["id_list"] == "math/0212237,0708.2247,2303.07061"

    def test_commas_and_slashes_stay_literal(self) -> None:
        url = build_id_list_url(["math/0212237", "0708.2247"])
        assert "id_list=math/0212237,0708.2247" in url
        assert url.startswith("https://export.arxiv.org/api/query?")

    def test_max_results_below_id_count_raises(self) -> None:
        with pytest.raises(ValueError, match="max_results"):
            build_id_list_url(["0708.2247", "2303.07061"], max_results=1)

    def test_explicit_max_results_at_least_id_count_ok(self) -> None:
        params = _query_params(
            build_id_list_url(["0708.2247"], max_results=20)
        )
        assert params["max_results"] == "20"

    def test_versioned_ids_accepted(self) -> None:
        params = _query_params(build_id_list_url(["math/0212237v1", "2307.01156v2"]))
        assert params["id_list"] == "math/0212237v1,2307.01156v2"

    def test_malformed_id_rejected_up_front(self) -> None:
        # One malformed id poisons the WHOLE id_list response
        # (HTTP-200 error feed) — pre-validate.
        with pytest.raises(ValueError, match="well-formed"):
            build_id_list_url(["0708.2247", "not-an-id"])

    def test_empty_id_list_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            build_id_list_url([])

    def test_over_page_cap_raises(self) -> None:
        ids = [f"2307.{i:05d}" for i in range(MAX_RESULTS_PER_PAGE + 1)]
        with pytest.raises(ValueError, match="cap"):
            build_id_list_url(ids)


class TestParseAtomMetadata:
    def test_old_style_round_trip(self) -> None:
        """t-atom-mapper acceptance: an old-style entry maps to a
        record with title/authors/abstract/year/categories populated,
        and the id round-trips UNVERSIONED with its prefix intact."""
        recs = parse_atom_metadata(
            _feed(_entry("http://arxiv.org/abs/math/0212237v1"))
        )
        assert len(recs) == 1
        r = recs[0]
        assert r.paper_id == "math/0212237"
        assert r.title == "Stability conditions on triangulated categories"
        assert r.authors == ("Tom Bridgeland",)
        assert r.abstract.startswith("We introduce")
        assert r.year == 2002
        assert r.categories == ("math.AG", "math.CT")
        assert r.primary_category == "math.AG"
        assert r.published == "2002-12-18T00:00:00Z"

    def test_new_style_version_stripped(self) -> None:
        recs = parse_atom_metadata(
            _feed(_entry("http://arxiv.org/abs/2307.01156v2"))
        )
        assert recs[0].paper_id == "2307.01156"

    def test_multiple_authors_in_order(self) -> None:
        recs = parse_atom_metadata(
            _feed(
                _entry(
                    "http://arxiv.org/abs/0708.2247v1",
                    authors=("Arend Bayer", "Emanuele Macrì"),
                )
            )
        )
        assert recs[0].authors == ("Arend Bayer", "Emanuele Macrì")

    def test_whitespace_collapsed_in_title_and_abstract(self) -> None:
        recs = parse_atom_metadata(
            _feed(
                _entry(
                    "http://arxiv.org/abs/2307.01156v1",
                    title="Stability conditions\n  on K3 surfaces",
                    summary="Line one.\n  Line two.",
                )
            )
        )
        assert recs[0].title == "Stability conditions on K3 surfaces"
        assert recs[0].abstract == "Line one. Line two."

    def test_unparseable_published_gives_year_zero(self) -> None:
        recs = parse_atom_metadata(
            _feed(_entry("http://arxiv.org/abs/2307.01156v1", published="soon"))
        )
        assert recs[0].year == 0
        assert recs[0].published == "soon"

    def test_error_entry_raises(self) -> None:
        feed = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<feed xmlns="http://www.w3.org/2005/Atom"'
            b' xmlns:arxiv="http://arxiv.org/schemas/atom">'
            b"<entry>"
            b"<id>http://arxiv.org/api/errors#incorrect_id_list</id>"
            b"<summary>malformed id_list</summary>"
            b"</entry></feed>"
        )
        with pytest.raises(RuntimeError, match="error entry"):
            parse_atom_metadata(feed)

    def test_non_xml_raises_runtimeerror(self) -> None:
        with pytest.raises(RuntimeError, match="non-XML"):
            parse_atom_metadata(b"<html><body>503 Service Unavailable")


class TestLegacyCandidateStability:
    """The m1 additions must NOT change ``parse_atom_feed`` — its
    (prefix-dropping) id extraction is byte-locked legacy behaviour
    for ``curate_seed`` / discovery callers."""

    def test_parse_atom_feed_still_drops_old_style_prefix(self) -> None:
        cands = parse_atom_feed(
            _feed(_entry("http://arxiv.org/abs/math/0212237v1"))
        )
        # Documented divergence: the LEGACY path loses the archive
        # prefix (this is exactly why parse_atom_metadata exists).
        assert cands[0].paper_id == "0212237"
        # The metadata path preserves it.
        recs = parse_atom_metadata(
            _feed(_entry("http://arxiv.org/abs/math/0212237v1"))
        )
        assert recs[0].paper_id == "math/0212237"
