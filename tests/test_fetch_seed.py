"""Unit tests for `tools.fetch_seed` and `tools.curate_seed` — offline parts.

The 50-paper fetch loop and the API call are gated on Phase 4 user
authorization; everything testable without network or LaTeXML lives here.
"""

from __future__ import annotations

from pathlib import Path

from tools.curate_seed import (
    Candidate,
    build_query_url,
    filter_candidates,
    parse_atom_feed,
)
from tools.fetch_seed import Outcome, read_seed_list, write_log


class TestSeedListReader:
    def test_skips_blanks_and_comments(self, tmp_path: Path):
        seed = tmp_path / "seed.txt"
        seed.write_text(
            "# header comment\n"
            "\n"
            "2307.01156\n"
            "  # indented comment\n"
            "1812.04567\n"
            "\n"
            "# trailing\n"
        )
        assert read_seed_list(seed) == ["2307.01156", "1812.04567"]

    def test_strips_whitespace(self, tmp_path: Path):
        seed = tmp_path / "seed.txt"
        seed.write_text("  2307.01156  \n\t1812.04567\t\n")
        assert read_seed_list(seed) == ["2307.01156", "1812.04567"]

    def test_empty_file(self, tmp_path: Path):
        seed = tmp_path / "seed.txt"
        seed.write_text("")
        assert read_seed_list(seed) == []

    def test_only_comments(self, tmp_path: Path):
        seed = tmp_path / "seed.txt"
        seed.write_text("# a\n# b\n")
        assert read_seed_list(seed) == []


class TestOutcomeLogFormat:
    def test_header_lines_and_summary_counts(self, tmp_path: Path):
        outcomes = [
            Outcome("2307.01156", True, "ok (12 math nodes, 50000 bytes)", 12.3),
            Outcome("1812.04567", False, "no <math> nodes — silent math loss", 8.7),
            Outcome("2401.00001", True, "ok (5 math nodes, 20000 bytes)", 15.2),
        ]
        log = tmp_path / "seed.log"
        write_log(log, outcomes, total_elapsed=120.5)
        text = log.read_text()
        assert "successes=2" in text
        assert "failures=1" in text
        assert "total_wall_clock_seconds=120.5" in text
        assert "2307.01156\tok\t12.3\tok (12 math nodes" in text
        assert "1812.04567\tfail\t8.7\tno <math> nodes" in text

    def test_log_creates_parent_dirs(self, tmp_path: Path):
        log = tmp_path / "ops" / "parser-failures" / "seed.log"
        write_log(log, [Outcome("2307.01156", True, "ok", 1.0)], total_elapsed=1.0)
        assert log.exists()


class TestCurateQueryURL:
    def test_includes_required_params(self):
        url = build_query_url("math.AG", start=0, max_results=200)
        assert "search_query=cat%3Amath.AG" in url
        assert "start=0" in url
        assert "max_results=200" in url
        assert "sortBy=submittedDate" in url
        assert "sortOrder=descending" in url

    def test_uses_export_host(self):
        url = build_query_url("math.AG", 0, 10)
        assert url.startswith("https://export.arxiv.org/api/query?")


class TestAtomFeedParsing:
    SAMPLE_FEED = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom"'
        ' xmlns:arxiv="http://arxiv.org/schemas/atom">\n'
        "  <entry>\n"
        "    <id>http://arxiv.org/abs/2307.01156v2</id>\n"
        "    <published>2023-07-04T18:30:00Z</published>\n"
        "    <summary>This is a sufficiently long abstract describing a paper about"
        " smooth projective varieties and their cohomological invariants under"
        " étale base change.</summary>\n"
        "    <author><name>A. Author</name></author>\n"
        "    <author><name>B. Coauthor</name></author>\n"
        '    <arxiv:primary_category term="math.AG"/>\n'
        "  </entry>\n"
        "  <entry>\n"
        "    <id>http://arxiv.org/abs/1812.04567v1</id>\n"
        "    <published>2018-12-11T09:15:00Z</published>\n"
        "    <summary>Short.</summary>\n"
        "    <author><name>C. Lone</name></author>\n"
        '    <arxiv:primary_category term="math.NT"/>\n'
        "  </entry>\n"
        "</feed>"
    )

    def test_extracts_paper_id_without_version(self):
        candidates = parse_atom_feed(self.SAMPLE_FEED.encode())
        ids = [c.paper_id for c in candidates]
        assert ids == ["2307.01156", "1812.04567"]

    def test_extracts_year(self):
        candidates = parse_atom_feed(self.SAMPLE_FEED.encode())
        assert candidates[0].submitted_year == 2023
        assert candidates[1].submitted_year == 2018

    def test_extracts_author_count(self):
        candidates = parse_atom_feed(self.SAMPLE_FEED.encode())
        assert candidates[0].n_authors == 2
        assert candidates[1].n_authors == 1

    def test_extracts_primary_category(self):
        candidates = parse_atom_feed(self.SAMPLE_FEED.encode())
        assert candidates[0].primary_category == "math.AG"
        assert candidates[1].primary_category == "math.NT"

    def test_truncates_abstract_head(self):
        candidates = parse_atom_feed(self.SAMPLE_FEED.encode())
        assert len(candidates[0].abstract_head) <= 120
        assert "smooth projective" in candidates[0].abstract_head


class TestFilterCandidates:
    def _candidate(
        self, *, paper_id: str, year: int, primary: str, abstract: str
    ) -> Candidate:
        return Candidate(
            paper_id=paper_id,
            submitted_year=year,
            n_authors=1,
            primary_category=primary,
            abstract_head=abstract,
        )

    def test_filters_by_primary_category(self):
        long_abstract = "x" * 250
        good = self._candidate(
            paper_id="2307.01156", year=2023, primary="math.AG", abstract=long_abstract
        )
        bad = self._candidate(
            paper_id="1812.04567", year=2023, primary="math.NT", abstract=long_abstract
        )
        kept = filter_candidates([good, bad], "math.AG", min_year=2015, min_abstract_chars=200)
        assert kept == [good]

    def test_filters_by_year(self):
        long_abstract = "x" * 250
        old = self._candidate(
            paper_id="1402.01156", year=2014, primary="math.AG", abstract=long_abstract
        )
        new = self._candidate(
            paper_id="2307.01156", year=2023, primary="math.AG", abstract=long_abstract
        )
        kept = filter_candidates([old, new], "math.AG", min_year=2015, min_abstract_chars=200)
        assert kept == [new]

    def test_filters_short_abstracts(self):
        short = self._candidate(
            paper_id="2307.01156", year=2023, primary="math.AG", abstract="brief"
        )
        good = self._candidate(
            paper_id="1812.04567", year=2023, primary="math.AG", abstract="x" * 250
        )
        kept = filter_candidates([short, good], "math.AG", min_year=2015, min_abstract_chars=200)
        assert kept == [good]
