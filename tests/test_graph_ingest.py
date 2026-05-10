"""Integration tests for E09_S01 — Kùzu schema + OpenAlex bulk ingest.

The test runs against a real Kùzu database (in ``tmp_path``) but mocks
the OpenAlex HTTP layer via ``monkeypatch.setattr`` on
``ingest.graph_ingest._fetch_openalex_work``. There is no live network
in CI; AC#8 ("integration test passes with mocked OpenAlex API")
requires this discipline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import kuzu
import pytest

from ingest import graph_ingest, kuzudb_schema

# ---------------------------------------------------------------------------
# Fixtures: 5-paper corpus per the brief deliverable list
# ---------------------------------------------------------------------------

# Paper id → mocked OpenAlex Work response. The corpus models a small
# citation graph where:
#   - P1 cites P2, P3, plus an external work that is NOT in the corpus.
#   - P2 cites nothing.
#   - P3 cites P5.
#   - P4 is NOT in OpenAlex at all (fetch returns None) — exercises the
#       "papers in the corpus but not in OpenAlex" risk-note path.
#   - P5 cites P1 (creates a cycle, so the test pins ordering doesn't
#       smuggle topological assumptions).
#
# Expected edges after ingest: 4 in-corpus edges
# (P1→P2, P1→P3, P3→P5, P5→P1) plus zero edges out of P4 (not in
# OpenAlex) and zero edges out of P2 (no references). The external
# work cited by P1 is dropped because it is not in the corpus reverse
# mapping (AC#4).

P1 = "2401.00001"
P2 = "2401.00002"
P3 = "2401.00003"
P4 = "2401.00004"  # not in OpenAlex
P5 = "2401.00005"

CORPUS_IDS = [P1, P2, P3, P4, P5]

W1 = "https://openalex.org/W1000001"
W2 = "https://openalex.org/W1000002"
W3 = "https://openalex.org/W1000003"
W5 = "https://openalex.org/W1000005"
W_EXTERNAL = "https://openalex.org/W9999999"  # not in our 5-paper corpus


def _work(
    *,
    oa_id: str,
    title: str,
    refs: list[str],
    year: int = 2024,
    authors: list[str] | None = None,
    abstract_words: list[str] | None = None,
    primary_topic: str | None = "Algebraic Geometry",
) -> dict[str, Any]:
    """Build a minimal OpenAlex Work dict with just the fields we read."""
    abstract_index = {}
    for i, word in enumerate(abstract_words or []):
        abstract_index.setdefault(word, []).append(i)
    return {
        "id": oa_id,
        "title": title,
        "publication_year": year,
        "abstract_inverted_index": abstract_index,
        "authorships": [{"author": {"display_name": n}} for n in (authors or [])],
        "referenced_works": refs,
        "primary_topic": {"display_name": primary_topic} if primary_topic else None,
        "topics": [],
    }


@pytest.fixture
def fixture_corpus() -> dict[str, dict[str, Any] | None]:
    """Mocked OpenAlex Works for the 5-paper test corpus."""
    return {
        P1: _work(
            oa_id=W1,
            title="Paper One",
            refs=[W2, W3, W_EXTERNAL],
            authors=["Alice Adams", "Bob Brown"],
            abstract_words=["zeta", "function", "introduction"],
        ),
        P2: _work(oa_id=W2, title="Paper Two", refs=[]),
        P3: _work(oa_id=W3, title="Paper Three", refs=[W5]),
        P4: None,  # not in OpenAlex
        P5: _work(oa_id=W5, title="Paper Five", refs=[W1]),
    }


@pytest.fixture
def stub_fetcher(
    monkeypatch: pytest.MonkeyPatch,
    fixture_corpus: dict[str, dict[str, Any] | None],
) -> list[str]:
    """Replace the live OpenAlex HTTP fetcher with a fixture-driven stub.

    Returns a list that records each arxiv_id the production code asked
    for; tests use it to assert no live calls and that resumability
    skips already-resolved papers.
    """
    fetched: list[str] = []

    def _stub(arxiv_id: str, contact_email: str) -> dict[str, Any] | None:
        fetched.append(arxiv_id)
        # The production code expects the stub to return None for "paper
        # not in OpenAlex" (404 path); raise KeyError if a test asks for
        # an arxiv_id not in the corpus, so a typo doesn't silently pass.
        if arxiv_id not in fixture_corpus:
            raise KeyError(f"unexpected arxiv_id in stub: {arxiv_id}")
        return fixture_corpus[arxiv_id]

    monkeypatch.setattr(graph_ingest, "_fetch_openalex_work", _stub)
    return fetched


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Per-test Kùzu DB directory under ``tmp_path``."""
    return tmp_path / "kuzu_test"


@pytest.fixture
def checkpoint_path(tmp_path: Path) -> Path:
    """Per-test checkpoint path under ``tmp_path``."""
    return tmp_path / "ops" / "graph-ingest-checkpoint.json"


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------


class TestSchemaMigration:
    def test_creates_papers_and_cites_tables(self, db_path: Path):
        kuzudb_schema.apply_schema(db_path)
        db = kuzu.Database(str(db_path))
        try:
            conn = kuzu.Connection(db)
            r = conn.execute("CALL show_tables() RETURN name, type")
            tables = {}
            while r.has_next():
                row = r.get_next()
                tables[row[0]] = row[1]
        finally:
            del db
        assert tables.get("papers") == "NODE"
        assert tables.get("cites") == "REL"

    def test_idempotent(self, db_path: Path):
        """AC#2: Schema migration is idempotent (run twice = no error)."""
        kuzudb_schema.apply_schema(db_path)
        # Re-run; must not raise. Implementation uses CREATE … IF NOT EXISTS.
        kuzudb_schema.apply_schema(db_path)
        kuzudb_schema.apply_schema(db_path)
        db = kuzu.Database(str(db_path))
        try:
            conn = kuzu.Connection(db)
            r = conn.execute("CALL show_tables() RETURN COUNT(*)")
            row = r.get_next()
            assert row[0] == 2  # exactly 2 tables, no duplicates
        finally:
            del db

    def test_creates_parent_directory(self, tmp_path: Path):
        nested = tmp_path / "deeply" / "nested" / "kuzu"
        kuzudb_schema.apply_schema(nested)
        # The Kùzu directory itself is materialized.
        assert nested.exists() or nested.parent.exists()


# ---------------------------------------------------------------------------
# Ingest — happy path
# ---------------------------------------------------------------------------


class TestIngestHappyPath:
    def test_creates_node_for_each_seed_paper(
        self,
        stub_fetcher: list[str],
        db_path: Path,
        checkpoint_path: Path,
    ):
        """AC#3: For each of the seed papers, a `papers` node exists."""
        graph_ingest.ingest(
            seed_ids=CORPUS_IDS,
            db_path=db_path,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )

        db = kuzu.Database(str(db_path))
        try:
            conn = kuzu.Connection(db)
            r = conn.execute("MATCH (p:papers) RETURN p.paper_id ORDER BY p.paper_id")
            paper_ids = []
            while r.has_next():
                paper_ids.append(r.get_next()[0])
        finally:
            del db
        assert paper_ids == sorted(CORPUS_IDS)

    def test_in_corpus_edges_only(
        self,
        stub_fetcher: list[str],
        db_path: Path,
        checkpoint_path: Path,
    ):
        """AC#4: cites edges are written for OpenAlex-confirmed in-corpus pairs."""
        graph_ingest.ingest(
            seed_ids=CORPUS_IDS,
            db_path=db_path,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )

        db = kuzu.Database(str(db_path))
        try:
            conn = kuzu.Connection(db)
            r = conn.execute(
                "MATCH (a:papers)-[r:cites]->(b:papers) "
                "RETURN a.paper_id, b.paper_id, r.source, r.confidence "
                "ORDER BY a.paper_id, b.paper_id"
            )
            edges = []
            while r.has_next():
                edges.append(tuple(r.get_next()))
        finally:
            del db

        # Expected: P1→P2, P1→P3, P3→P5, P5→P1 (cycle via P5).
        # External work cited by P1 must NOT appear (not in corpus).
        # P4 has no edges (not in OpenAlex).
        # P2 has no outgoing edges (no references).
        assert edges == [
            (P1, P2, "openAlex", pytest.approx(1.0)),
            (P1, P3, "openAlex", pytest.approx(1.0)),
            (P3, P5, "openAlex", pytest.approx(1.0)),
            (P5, P1, "openAlex", pytest.approx(1.0)),
        ]

    def test_paper_not_in_openalex_writes_node_no_edges(
        self,
        stub_fetcher: list[str],
        db_path: Path,
        checkpoint_path: Path,
    ):
        """Risk-note: papers not in OpenAlex still get a node (NULL oa_work_id)
        but no edges originate from them."""
        graph_ingest.ingest(
            seed_ids=CORPUS_IDS,
            db_path=db_path,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )

        db = kuzu.Database(str(db_path))
        try:
            conn = kuzu.Connection(db)
            r = conn.execute(
                "MATCH (p:papers {paper_id: $id}) "
                "RETURN p.oa_work_id, p.title, p.year",
                {"id": P4},
            )
            row = r.get_next()
            assert row[0] is None  # NULL oa_work_id
            assert row[1] == ""
            assert row[2] is None
            # P4 has zero outgoing edges
            r2 = conn.execute(
                "MATCH (a:papers {paper_id: $id})-[:cites]->() RETURN COUNT(*)",
                {"id": P4},
            )
            assert r2.get_next()[0] == 0
        finally:
            del db

    def test_metadata_populated_from_openalex(
        self,
        stub_fetcher: list[str],
        db_path: Path,
        checkpoint_path: Path,
    ):
        graph_ingest.ingest(
            seed_ids=CORPUS_IDS,
            db_path=db_path,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )
        db = kuzu.Database(str(db_path))
        try:
            conn = kuzu.Connection(db)
            r = conn.execute(
                "MATCH (p:papers {paper_id: $id}) "
                "RETURN p.title, p.authors, p.year, p.abstract, p.oa_work_id",
                {"id": P1},
            )
            row = r.get_next()
        finally:
            del db
        title, authors, year, abstract, oa_work_id = row
        assert title == "Paper One"
        assert authors == "Alice Adams, Bob Brown"
        assert year == 2024
        assert abstract == "zeta function introduction"
        assert oa_work_id == "W1000001"


# ---------------------------------------------------------------------------
# Idempotency / resume
# ---------------------------------------------------------------------------


class TestResume:
    def test_re_ingest_is_idempotent(
        self,
        stub_fetcher: list[str],
        db_path: Path,
        checkpoint_path: Path,
    ):
        """Run ingest twice; node + edge counts must not double."""
        graph_ingest.ingest(
            seed_ids=CORPUS_IDS,
            db_path=db_path,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )
        # The second pass should issue no fetch calls because all papers
        # are already in the checkpoint.
        before_calls = len(stub_fetcher)
        graph_ingest.ingest(
            seed_ids=CORPUS_IDS,
            db_path=db_path,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )
        assert len(stub_fetcher) == before_calls

        db = kuzu.Database(str(db_path))
        try:
            conn = kuzu.Connection(db)
            paper_count = conn.execute(
                "MATCH (p:papers) RETURN COUNT(*)"
            ).get_next()[0]
            edge_count = conn.execute(
                "MATCH ()-[r:cites]->() RETURN COUNT(*)"
            ).get_next()[0]
        finally:
            del db
        assert paper_count == len(CORPUS_IDS)
        assert edge_count == 4

    def test_resume_from_checkpoint_skips_resolved_papers(
        self,
        stub_fetcher: list[str],
        db_path: Path,
        checkpoint_path: Path,
    ):
        """AC#6: re-run after interruption skips already-resolved papers."""
        # Pre-seed a checkpoint as if 2 papers had already been resolved.
        # Construct one in the on-disk format so the test exercises the
        # deserialization path.
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_path.write_text(
            json.dumps(
                {
                    "resolved": {
                        P1: {
                            "oa_work_id": "W1000001",
                            "title": "Paper One",
                            "abstract": "",
                            "authors": "",
                            "year": 2024,
                            "categories": "",
                            "referenced_works": ["W1000002", "W1000003"],
                        },
                        P2: {
                            "oa_work_id": "W1000002",
                            "title": "Paper Two",
                            "abstract": "",
                            "authors": "",
                            "year": 2024,
                            "categories": "",
                            "referenced_works": [],
                        },
                    },
                    "edges_done": [],
                }
            )
        )

        graph_ingest.ingest(
            seed_ids=CORPUS_IDS,
            db_path=db_path,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )

        # Only P3, P4, P5 should have been fetched (P1 + P2 in checkpoint).
        assert sorted(stub_fetcher) == sorted([P3, P4, P5])

    def test_checkpoint_atomic_write_no_tmp_left_behind(
        self,
        stub_fetcher: list[str],
        db_path: Path,
        checkpoint_path: Path,
    ):
        graph_ingest.ingest(
            seed_ids=CORPUS_IDS,
            db_path=db_path,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )
        # The .tmp sibling must not survive a successful ingest.
        tmp_sibling = checkpoint_path.with_suffix(checkpoint_path.suffix + ".tmp")
        assert not tmp_sibling.exists()
        # The real checkpoint exists and parses.
        payload = json.loads(checkpoint_path.read_text())
        assert set(payload["resolved"].keys()) == set(CORPUS_IDS)
        assert sorted(payload["edges_done"]) == sorted(CORPUS_IDS)


# ---------------------------------------------------------------------------
# Validation / safety
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_paper_id_rejected_before_any_io(
        self,
        stub_fetcher: list[str],
        db_path: Path,
        checkpoint_path: Path,
    ):
        """Threat 1 (08-security-observability-ops.md): every paper_id is
        regex-validated before any HTTP / DB write."""
        with pytest.raises(ValueError):
            graph_ingest.ingest(
                seed_ids=[P1, "../../etc/passwd"],
                db_path=db_path,
                checkpoint_path=checkpoint_path,
                contact_email="test@example.com",
                sleep_seconds=0,
            )
        # No HTTP fetch happened — validation precedes any network.
        assert stub_fetcher == []

    def test_no_live_network_calls_in_test_run(
        self,
        stub_fetcher: list[str],
        db_path: Path,
        checkpoint_path: Path,
    ):
        """Sanity guard: the live fetcher must be replaced for the entire
        test run. If a future refactor breaks the monkeypatch wiring,
        this test catches it."""
        graph_ingest.ingest(
            seed_ids=CORPUS_IDS,
            db_path=db_path,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )
        # All fetched IDs are corpus IDs — the stub raised KeyError on
        # any other.
        assert set(stub_fetcher) <= set(CORPUS_IDS)


# ---------------------------------------------------------------------------
# Polite-pool URL composition (AC#7)
# ---------------------------------------------------------------------------


class TestPolitePool:
    def test_user_agent_contains_arxmcp_and_mailto(self):
        """AC#7: User-Agent header includes ``arXMCP/0.1 (mailto:...)``."""
        # build_user_agent is the helper we delegate to. Invoke directly
        # to confirm the format string is the one the AC pins.
        from tools.arxiv_fetch import build_user_agent

        ua = build_user_agent("operator@example.com")
        assert ua.startswith("arXMCP/0.1 (mailto:")
        assert "operator@example.com" in ua
        assert ua.endswith(")")

    def test_works_url_includes_mailto_query_param(self):
        """OpenAlex polite pool: ``?mailto=`` query string on every call."""
        url = graph_ingest._build_works_url(P1, "operator@example.com")
        assert "mailto=operator%40example.com" in url
        assert url.startswith("https://api.openalex.org/works/")

    def test_works_url_encodes_inner_arxiv_url(self):
        url = graph_ingest._build_works_url(P1, "x@y")
        # The inner https:// must be percent-encoded so a proxy doesn't
        # mistake it for a path component.
        assert "https%3A%2F%2Farxiv.org%2Fabs%2F2401.00001" in url


# ---------------------------------------------------------------------------
# OpenAlex parsers (small unit tests for the projection helpers)
# ---------------------------------------------------------------------------


class TestParsers:
    def test_strip_oa_url_strips_prefix(self):
        assert graph_ingest._strip_oa_url("https://openalex.org/W123") == "W123"

    def test_strip_oa_url_passthrough_when_no_prefix(self):
        assert graph_ingest._strip_oa_url("W123") == "W123"

    def test_reconstruct_abstract_from_inverted_index(self):
        work = {
            "abstract_inverted_index": {"hello": [0, 3], "world": [1], "foo": [2]}
        }
        assert graph_ingest._reconstruct_abstract(work) == "hello world foo hello"

    def test_reconstruct_abstract_empty_when_index_missing(self):
        assert graph_ingest._reconstruct_abstract({}) == ""
        assert graph_ingest._reconstruct_abstract({"abstract_inverted_index": None}) == ""

    def test_format_authors_joins_display_names(self):
        authorships = [
            {"author": {"display_name": "A. Author"}},
            {"author": {"display_name": "B. Boffin"}},
            {"author": {}},  # missing display_name dropped
        ]
        assert graph_ingest._format_authors(authorships) == "A. Author, B. Boffin"

    def test_format_authors_handles_none(self):
        assert graph_ingest._format_authors(None) == ""
        assert graph_ingest._format_authors([]) == ""

    def test_format_categories_dedupes(self):
        work = {
            "primary_topic": {"display_name": "Algebraic Geometry"},
            "topics": [
                {"display_name": "Algebraic Geometry"},  # duplicate of primary
                {"display_name": "Number Theory"},
            ],
        }
        assert graph_ingest._format_categories(work) == "Algebraic Geometry, Number Theory"

    def test_resolved_from_work_blank_when_none(self):
        rw = graph_ingest._resolved_from_work(None)
        assert rw.oa_work_id is None
        assert rw.title == ""
        assert rw.referenced_works == ()

    def test_resolved_from_work_strips_referenced_url_prefixes(self):
        work = _work(
            oa_id=W1,
            title="t",
            refs=["https://openalex.org/W2", "https://openalex.org/W3"],
        )
        rw = graph_ingest._resolved_from_work(work)
        assert rw.referenced_works == ("W2", "W3")


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


class TestCLI:
    def test_category_flag_is_not_implemented(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """The brief's --category bulk-discovery path is intentionally
        not wired up because the brief's stated Concept IDs were
        verified live as wrong/deprecated. The CLI must emit a clear
        error rather than silently succeeding."""
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text(f"{P1}\n", encoding="utf-8")
        rc = graph_ingest.main(
            [
                "--seed-file",
                str(seed_file),
                "--checkpoint",
                str(tmp_path / "ck.json"),
                "--kuzudb",
                str(tmp_path / "kuzu"),
                "--category",
                "math.AG",
            ]
        )
        assert rc == 2
        captured = capsys.readouterr()
        assert "not implemented" in captured.err.lower()

    def test_missing_contact_email_errors(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        monkeypatch.delenv("ARXMCP_CONTACT_EMAIL", raising=False)
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text(f"{P1}\n", encoding="utf-8")
        rc = graph_ingest.main(
            [
                "--seed-file",
                str(seed_file),
                "--checkpoint",
                str(tmp_path / "ck.json"),
                "--kuzudb",
                str(tmp_path / "kuzu"),
            ]
        )
        assert rc == 2
        captured = capsys.readouterr()
        assert "ARXMCP_CONTACT_EMAIL" in captured.err

    def test_empty_seed_file_errors(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("# only a comment\n\n", encoding="utf-8")
        rc = graph_ingest.main(
            [
                "--seed-file",
                str(seed_file),
                "--checkpoint",
                str(tmp_path / "ck.json"),
                "--kuzudb",
                str(tmp_path / "kuzu"),
            ]
        )
        assert rc == 2
        captured = capsys.readouterr()
        assert "no IDs" in captured.err
