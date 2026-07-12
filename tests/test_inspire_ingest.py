"""Integration tests for E09_S02 — INSPIRE-HEP enrichment.

Mirrors the discipline of ``tests/test_graph_ingest.py``: real Kùzu
DB in ``tmp_path``, mocked HTTP layer via ``monkeypatch.setattr`` on
``ingest.inspire_ingest._fetch_inspire_record``. AC#5 (integration
test passes with mocked API) requires this — CI never makes live
INSPIRE calls.

Notable test design:

- A synthetic 5-paper corpus that includes hep-th, math-ph, math.AG
  (skipped by the post-fetch physics gate), and a paper with no
  INSPIRE record. The seed corpus (`tools/seed-papers.txt`) is
  all math.AG and would not exercise the INSPIRE path at all; the
  integration test must construct a synthetic graph.
- Tests for the F4 split-writer property: an INSPIRE re-MERGE must
  NOT clobber the OpenAlex-owned columns (``title``, ``abstract``,
  etc.), and an OpenAlex re-MERGE must NOT clobber INSPIRE's
  ``journal_ref`` / ``doi`` / ``inspire_id``.
- Cross-source edge co-existence: AC#3 ("existing source=openAlex
  edges are not duplicated or overwritten") is satisfied by the
  ``MERGE (a)-[r:cites {source: $source}]->(b)`` key. Tests pin
  this by emitting both an OpenAlex and an INSPIRE edge between
  the same (a, b) pair and asserting both edges exist.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import kuzu
import pytest

from ingest import graph_ingest, inspire_ingest, kuzudb_schema
from tests._graph_helpers import kuzu_reopen_unsupported_on_windows

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Five synthetic papers representing the cases the milestone must handle.
P_HEP_TH = "2401.10001"  # hep-th, in INSPIRE, references P_MATH_PH (in corpus)
P_MATH_PH = "2401.10002"  # math-ph, in INSPIRE, no references
P_HEP_TH_2 = "2401.10003"  # hep-th, in INSPIRE, references an external arXiv id
P_MATH_AG = "2401.10004"  # math.AG, IS in INSPIRE but post-fetch gate filters out
P_NOT_IN_INSPIRE = "2401.10005"  # 404 — no INSPIRE record

CORPUS_IDS = [P_HEP_TH, P_MATH_PH, P_HEP_TH_2, P_MATH_AG, P_NOT_IN_INSPIRE]
EXTERNAL_REF = "9999.99999"  # cited by P_HEP_TH_2 but not in our corpus


def _record(
    *,
    control_number: int,
    arxiv_categories: list[str],
    refs_arxiv: list[str],
    doi: str | None = None,
    journal_title: str | None = None,
    journal_volume: str | None = None,
    year: int | None = None,
) -> dict[str, Any]:
    """Build a minimal INSPIRE-HEP Work response dict.

    Only the fields ``_resolved_from_inspire`` reads. Real responses
    have many more keys; the test pins what we depend on, mirroring
    R1's "snapshot fixture" recommendation in spirit.
    """
    metadata: dict[str, Any] = {
        "control_number": control_number,
        "arxiv_eprints": [{"value": "stub", "categories": arxiv_categories}],
        "references": [
            {"reference": {"arxiv_eprint": eprint}} for eprint in refs_arxiv
        ],
    }
    if doi:
        metadata["dois"] = [{"value": doi}]
    if journal_title or journal_volume or year:
        pub: dict[str, Any] = {}
        if journal_title:
            pub["journal_title"] = journal_title
        if journal_volume:
            pub["journal_volume"] = journal_volume
        if year:
            pub["year"] = year
        metadata["publication_info"] = [pub]
    return {"metadata": metadata}


@pytest.fixture
def fixture_corpus() -> dict[str, dict[str, Any] | None]:
    """Mocked INSPIRE responses for the 5-paper synthetic corpus."""
    return {
        P_HEP_TH: _record(
            control_number=1000001,
            arxiv_categories=["hep-th"],
            refs_arxiv=[P_MATH_PH],
            doi="10.1234/hep.001",
            journal_title="Phys. Rev. D",
            journal_volume="100",
            year=2024,
        ),
        P_MATH_PH: _record(
            control_number=1000002,
            arxiv_categories=["math-ph"],
            refs_arxiv=[],
            doi="10.1234/mph.002",
            journal_title="Commun. Math. Phys.",
            journal_volume="380",
            year=2024,
        ),
        P_HEP_TH_2: _record(
            control_number=1000003,
            arxiv_categories=["hep-th", "math-ph"],
            refs_arxiv=[EXTERNAL_REF, P_HEP_TH],  # one external, one in corpus
            doi=None,
            journal_title=None,
        ),
        P_MATH_AG: _record(
            control_number=1000004,
            arxiv_categories=["math.AG"],  # NOT in PHYSICS_CATEGORIES
            refs_arxiv=[P_HEP_TH],
            doi="10.1234/ag.004",
            journal_title="J. Algebraic Geom.",
        ),
        P_NOT_IN_INSPIRE: None,
    }


@pytest.fixture
def stub_fetcher(
    monkeypatch: pytest.MonkeyPatch,
    fixture_corpus: dict[str, dict[str, Any] | None],
) -> list[str]:
    """Replace the live INSPIRE HTTP fetcher with a fixture-driven stub."""
    fetched: list[str] = []

    def _stub(arxiv_id: str, contact_email: str) -> dict[str, Any] | None:
        fetched.append(arxiv_id)
        if arxiv_id not in fixture_corpus:
            raise KeyError(f"unexpected arxiv_id in stub: {arxiv_id}")
        return fixture_corpus[arxiv_id]

    monkeypatch.setattr(inspire_ingest, "_fetch_inspire_record", _stub)
    return fetched


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "kuzu_test"


@pytest.fixture
def checkpoint_path(tmp_path: Path) -> Path:
    return tmp_path / "ops" / "inspire-ingest-checkpoint.json"


@pytest.fixture
def populated_db(db_path: Path) -> Path:
    """Pre-populate the Kùzu DB with the 5 synthetic ``papers`` nodes
    (no INSPIRE-owned columns set — those are what the test verifies
    INSPIRE writes). Mirrors the production state where the OpenAlex
    ingest has run first.
    """
    kuzudb_schema.apply_schema(db_path)
    db = kuzu.Database(str(db_path))
    try:
        conn = kuzu.Connection(db)
        for arxiv_id in CORPUS_IDS:
            conn.execute(
                """
                MERGE (p:papers {paper_id: $id})
                ON CREATE SET p.title = $title, p.year = 2024,
                              p.categories = ''
                """,
                {"id": arxiv_id, "title": f"openalex-{arxiv_id}"},
            )
    finally:
        del db
    return db_path


# ---------------------------------------------------------------------------
# Schema v2 migration
# ---------------------------------------------------------------------------


class TestSchemaV2:
    def test_apply_schema_adds_v2_columns(self, db_path: Path):
        """E09_S02 schema bump: ``papers`` gains ``doi``, ``journal_ref``,
        ``inspire_id`` columns; ``KUZU_SCHEMA_VERSION = 2``."""
        kuzudb_schema.apply_schema(db_path)
        db = kuzu.Database(str(db_path))
        try:
            conn = kuzu.Connection(db)
            cols = kuzudb_schema._introspect_columns(conn, "papers")
        finally:
            del db
        assert "doi" in cols
        assert "journal_ref" in cols
        assert "inspire_id" in cols

    def test_schema_version_is_2(self, db_path: Path):
        kuzudb_schema.apply_schema(db_path)
        assert kuzudb_schema.read_schema_version(db_path) == 2
        assert kuzudb_schema.KUZU_SCHEMA_VERSION == 2

    def test_v1_to_v2_migration_is_idempotent(self, db_path: Path):
        """Apply schema repeatedly; each subsequent run is a no-op (no
        duplicate-column error from the ALTER block)."""
        kuzudb_schema.apply_schema(db_path)
        kuzudb_schema.apply_schema(db_path)
        kuzudb_schema.apply_schema(db_path)
        db = kuzu.Database(str(db_path))
        try:
            conn = kuzu.Connection(db)
            cols = kuzudb_schema._introspect_columns(conn, "papers")
        finally:
            del db
        assert {"doi", "journal_ref", "inspire_id"}.issubset(cols)

    @kuzu_reopen_unsupported_on_windows
    def test_simulated_v1_db_migrates_to_v2(self, tmp_path: Path):
        """Stand up a V1-shaped DB by hand (without the v2 ALTERs) and
        verify ``apply_schema`` brings it up to v2 without error."""
        db_path = tmp_path / "kuzu_v1"
        db = kuzu.Database(str(db_path))
        try:
            conn = kuzu.Connection(db)
            # Apply only the v1 statements (no v2 ALTERs).
            for stmt in kuzudb_schema.SCHEMA_STATEMENTS:
                conn.execute(stmt)
            # Stamp v1 explicitly.
            conn.execute(
                "MERGE (m:_schema_meta {key: $k}) "
                "ON CREATE SET m.value = 1 "
                "ON MATCH SET m.value = 1",
                {"k": "version"},
            )
        finally:
            del db
        # Sanity: v1 papers does not have v2 columns yet.
        db = kuzu.Database(str(db_path))
        try:
            conn = kuzu.Connection(db)
            cols_before = kuzudb_schema._introspect_columns(conn, "papers")
            assert "doi" not in cols_before
        finally:
            del db
        # Apply v2 migration.
        kuzudb_schema.apply_schema(db_path)
        # Verify v2 state.
        assert kuzudb_schema.read_schema_version(db_path) == 2
        db = kuzu.Database(str(db_path))
        try:
            conn = kuzu.Connection(db)
            cols_after = kuzudb_schema._introspect_columns(conn, "papers")
        finally:
            del db
        assert {"doi", "journal_ref", "inspire_id"}.issubset(cols_after)


# ---------------------------------------------------------------------------
# Resolved-Inspire dataclass + parsers
# ---------------------------------------------------------------------------


class TestParsers:
    def test_format_journal_ref_full(self):
        work = _record(
            control_number=1,
            arxiv_categories=["hep-th"],
            refs_arxiv=[],
            journal_title="Phys. Rev. D",
            journal_volume="100",
            year=2024,
        )
        assert (
            inspire_ingest._format_journal_ref(work) == "Phys. Rev. D 100 (2024)"
        )

    def test_format_journal_ref_partial(self):
        work = _record(
            control_number=1,
            arxiv_categories=["hep-th"],
            refs_arxiv=[],
            journal_title="JHEP",
        )
        assert inspire_ingest._format_journal_ref(work) == "JHEP"

    def test_format_journal_ref_none(self):
        assert inspire_ingest._format_journal_ref({}) is None
        assert inspire_ingest._format_journal_ref({"metadata": {}}) is None

    def test_extract_arxiv_categories_dedup(self):
        work = {
            "metadata": {
                "arxiv_eprints": [
                    {"categories": ["hep-th", "math-ph"]},
                    {"categories": ["hep-th", "gr-qc"]},
                ]
            }
        }
        # Order preserved; deduped.
        assert inspire_ingest._extract_arxiv_categories(work) == (
            "hep-th",
            "math-ph",
            "gr-qc",
        )

    def test_extract_references_arxiv_drops_missing_eprints(self):
        work = {
            "metadata": {
                "references": [
                    {"reference": {"arxiv_eprint": "1207.7214"}},
                    {"reference": {}},  # no eprint — drop
                    {"reference": {"arxiv_eprint": "1502.06120"}},
                    {"reference": {"arxiv_eprint": "1207.7214"}},  # dup — drop
                ]
            }
        }
        assert inspire_ingest._extract_references_arxiv(work) == (
            "1207.7214",
            "1502.06120",
        )

    def test_resolved_from_inspire_blank_when_none(self):
        ri = inspire_ingest._resolved_from_inspire(None)
        assert ri.inspire_id is None
        assert ri.doi is None
        assert ri.journal_ref is None
        assert ri.references_arxiv == ()
        assert ri.arxiv_categories == ()

    def test_resolved_from_inspire_full(self):
        work = _record(
            control_number=42,
            arxiv_categories=["hep-th"],
            refs_arxiv=["1207.7214"],
            doi="10.1234/foo",
            journal_title="JHEP",
            year=2024,
        )
        ri = inspire_ingest._resolved_from_inspire(work)
        assert ri.inspire_id == "42"
        assert ri.doi == "10.1234/foo"
        assert ri.journal_ref == "JHEP (2024)"
        assert ri.references_arxiv == ("1207.7214",)
        assert ri.arxiv_categories == ("hep-th",)


# ---------------------------------------------------------------------------
# URL composition
# ---------------------------------------------------------------------------


class TestURLComposition:
    def test_record_url_includes_fields_filter(self):
        url = inspire_ingest._build_record_url(P_HEP_TH)
        assert url.startswith("https://inspirehep.net/api/arxiv/")
        assert "fields=" in url
        # The fields request must include the keys the parser depends on.
        for field in ("control_number", "references", "dois", "publication_info"):
            assert field in url, f"expected {field!r} in URL: {url}"

    def test_record_url_encodes_arxiv_id(self):
        # Old-style arXiv IDs contain a slash; must be percent-encoded.
        url = inspire_ingest._build_record_url("hep-ph/0603175")
        assert "hep-ph%2F0603175" in url


# ---------------------------------------------------------------------------
# Enrichment happy path
# ---------------------------------------------------------------------------


class TestEnrichHappyPath:
    def test_inspire_columns_populated_only_for_physics_papers(
        self,
        stub_fetcher: list[str],
        populated_db: Path,
        checkpoint_path: Path,
    ):
        """AC#4: ``doi`` and ``inspire_id`` are populated where INSPIRE
        returns them. The post-fetch physics gate prevents math.AG papers
        from being enriched even when INSPIRE has a record for them."""
        inspire_ingest.enrich(
            paper_ids=CORPUS_IDS,
            db_path=populated_db,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )

        db = kuzu.Database(str(populated_db))
        try:
            conn = kuzu.Connection(db)
            r = conn.execute(
                "MATCH (p:papers) RETURN p.paper_id, p.doi, p.inspire_id, "
                "p.journal_ref ORDER BY p.paper_id"
            )
            rows = []
            while r.has_next():
                rows.append(tuple(r.get_next()))
        finally:
            del db
        by_id = {row[0]: row for row in rows}

        # hep-th paper enriched.
        assert by_id[P_HEP_TH][1] == "10.1234/hep.001"
        assert by_id[P_HEP_TH][2] == "1000001"
        assert by_id[P_HEP_TH][3] == "Phys. Rev. D 100 (2024)"
        # math-ph paper enriched.
        assert by_id[P_MATH_PH][1] == "10.1234/mph.002"
        assert by_id[P_MATH_PH][2] == "1000002"
        # hep-th-and-math-ph paper enriched (no DOI was supplied).
        assert by_id[P_HEP_TH_2][1] is None
        assert by_id[P_HEP_TH_2][2] == "1000003"
        # math.AG paper NOT enriched (post-fetch gate).
        assert by_id[P_MATH_AG][1] is None
        assert by_id[P_MATH_AG][2] is None
        # Paper not in INSPIRE — also not enriched.
        assert by_id[P_NOT_IN_INSPIRE][1] is None

    def test_in_corpus_inspire_edges(
        self,
        stub_fetcher: list[str],
        populated_db: Path,
        checkpoint_path: Path,
    ):
        """AC#2: cites edges with ``source="inspire"`` are emitted only
        for in-corpus reference pairs from physics-gated papers."""
        inspire_ingest.enrich(
            paper_ids=CORPUS_IDS,
            db_path=populated_db,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )

        db = kuzu.Database(str(populated_db))
        try:
            conn = kuzu.Connection(db)
            r = conn.execute(
                "MATCH (a:papers)-[r:cites]->(b:papers) "
                "WHERE r.source = 'inspire' "
                "RETURN a.paper_id, b.paper_id ORDER BY a.paper_id"
            )
            edges = []
            while r.has_next():
                edges.append(tuple(r.get_next()))
        finally:
            del db
        # Expected:
        #   P_HEP_TH -> P_MATH_PH (in-corpus reference)
        #   P_HEP_TH_2 -> P_HEP_TH (the other ref, EXTERNAL_REF, is not in
        #                            the corpus and is dropped)
        # Math.AG paper had P_HEP_TH as a reference but the post-fetch
        # gate removed it from `resolved` with empty references_arxiv,
        # so no edge emerges from there.
        assert (P_HEP_TH, P_MATH_PH) in edges
        assert (P_HEP_TH_2, P_HEP_TH) in edges
        # Math.AG paper had P_HEP_TH as a "reference" in the fixture, but
        # because the gate cleared its references_arxiv, no edge from it.
        assert all(src != P_MATH_AG for src, _ in edges)


class TestF4SplitWriter:
    """F4 closure: ``_merge_paper_inspire`` must NOT touch OpenAlex-owned
    columns, and the OpenAlex ``_merge_paper`` must not touch INSPIRE-owned
    columns."""

    def test_inspire_writer_does_not_touch_openalex_columns(
        self,
        stub_fetcher: list[str],
        populated_db: Path,
        checkpoint_path: Path,
    ):
        """The pre-populated DB has ``title=openalex-<id>`` for every
        paper. After INSPIRE enrichment, those titles must be unchanged."""
        inspire_ingest.enrich(
            paper_ids=CORPUS_IDS,
            db_path=populated_db,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )
        db = kuzu.Database(str(populated_db))
        try:
            conn = kuzu.Connection(db)
            r = conn.execute(
                "MATCH (p:papers) RETURN p.paper_id, p.title "
                "ORDER BY p.paper_id"
            )
            titles = {}
            while r.has_next():
                row = r.get_next()
                titles[row[0]] = row[1]
        finally:
            del db
        # Every paper's title is still the OpenAlex-stub value the
        # populated_db fixture wrote.
        for arxiv_id in CORPUS_IDS:
            assert titles[arxiv_id] == f"openalex-{arxiv_id}", (
                f"INSPIRE re-MERGE clobbered title for {arxiv_id} — F4 regression"
            )

    def test_openalex_writer_does_not_touch_inspire_columns(
        self,
        stub_fetcher: list[str],
        populated_db: Path,
        checkpoint_path: Path,
    ):
        """After INSPIRE enrichment, simulating an OpenAlex re-ingest must
        NOT clobber INSPIRE-owned columns. ``graph_ingest._merge_paper``
        only sets OpenAlex-owned columns."""
        # First: enrich via INSPIRE.
        inspire_ingest.enrich(
            paper_ids=CORPUS_IDS,
            db_path=populated_db,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )
        # Then: simulate a re-MERGE via the OpenAlex writer.
        from ingest.graph_ingest import _merge_paper, _ResolvedWork

        db = kuzu.Database(str(populated_db))
        try:
            conn = kuzu.Connection(db)
            for arxiv_id in CORPUS_IDS:
                _merge_paper(
                    conn,
                    arxiv_id,
                    _ResolvedWork(
                        oa_work_id="W_REINGEST",
                        title=f"openalex-{arxiv_id}",
                        abstract="",
                        authors="",
                        year=2024,
                        categories="",
                        referenced_works=(),
                    ),
                )
            # Now read back INSPIRE-owned columns.
            r = conn.execute(
                "MATCH (p:papers {paper_id: $id}) "
                "RETURN p.doi, p.inspire_id, p.journal_ref",
                {"id": P_HEP_TH},
            )
            row = r.get_next()
        finally:
            del db
        assert row[0] == "10.1234/hep.001", (
            "OpenAlex re-MERGE clobbered INSPIRE doi — F4 regression"
        )
        assert row[1] == "1000001", (
            "OpenAlex re-MERGE clobbered INSPIRE inspire_id — F4 regression"
        )
        assert row[2] == "Phys. Rev. D 100 (2024)", (
            "OpenAlex re-MERGE clobbered INSPIRE journal_ref — F4 regression"
        )


class TestCrossSourceEdges:
    """AC#3: existing OpenAlex edges are not duplicated or overwritten when
    INSPIRE writes its own edges. The MERGE-key composition (source is part
    of the edge identity) is the structural guarantee."""

    @kuzu_reopen_unsupported_on_windows
    def test_both_sources_edges_coexist(
        self,
        stub_fetcher: list[str],
        populated_db: Path,
        checkpoint_path: Path,
    ):
        # Pre-populate an OpenAlex edge between P_HEP_TH and P_MATH_PH.
        db = kuzu.Database(str(populated_db))
        try:
            conn = kuzu.Connection(db)
            graph_ingest._merge_cite(
                conn,
                src_paper_id=P_HEP_TH,
                dst_paper_id=P_MATH_PH,
                source="openAlex",
                confidence=1.0,
            )
        finally:
            del db

        # Now run the INSPIRE enrichment; INSPIRE will also emit an edge
        # P_HEP_TH -> P_MATH_PH with source="inspire".
        inspire_ingest.enrich(
            paper_ids=CORPUS_IDS,
            db_path=populated_db,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )

        db = kuzu.Database(str(populated_db))
        try:
            conn = kuzu.Connection(db)
            r = conn.execute(
                "MATCH (a:papers {paper_id: $a})-[r:cites]->(b:papers {paper_id: $b}) "
                "RETURN r.source ORDER BY r.source",
                {"a": P_HEP_TH, "b": P_MATH_PH},
            )
            sources = []
            while r.has_next():
                sources.append(r.get_next()[0])
        finally:
            del db
        # Both edges co-exist; AC#3 is satisfied.
        assert sources == ["inspire", "openAlex"]


# ---------------------------------------------------------------------------
# Failure / resume / collision (F-finding inheritance)
# ---------------------------------------------------------------------------


class TestE09S02RectificationGuards:
    """Regression tests for findings closed by the E09_S02 rect commit.

    Each test corresponds to a finding (F1, F2, F4, F5, F6, F8). The
    tests pin the rectified behavior so a future refactor can't
    silently re-open a closed finding.
    """

    @kuzu_reopen_unsupported_on_windows
    def test_f1_inspire_remerge_preserves_doi_when_response_drops_field(
        self, populated_db: Path
    ):
        """F1: a re-MERGE where the new INSPIRE response is missing
        ``doi`` / ``journal_ref`` / ``inspire_id`` MUST NOT clobber
        previously-stamped values. ``COALESCE`` in ON MATCH SET is the
        fix; this test fails on the pre-fix code."""
        # Stamp canonical INSPIRE values.
        first = inspire_ingest._ResolvedInspire(
            inspire_id="42",
            doi="10.1234/CANONICAL",
            journal_ref="JHEP (2024)",
            references_arxiv=(),
            arxiv_categories=("hep-th",),
        )
        db = kuzu.Database(str(populated_db))
        try:
            conn = kuzu.Connection(db)
            inspire_ingest._merge_paper_inspire(conn, P_HEP_TH, first)
        finally:
            del db

        # Now re-MERGE with NULL values — simulates a transient API
        # regression returning an incomplete record.
        second = inspire_ingest._ResolvedInspire(
            inspire_id=None,
            doi=None,
            journal_ref=None,
            references_arxiv=(),
            arxiv_categories=("hep-th",),
        )
        db = kuzu.Database(str(populated_db))
        try:
            conn = kuzu.Connection(db)
            inspire_ingest._merge_paper_inspire(conn, P_HEP_TH, second)
            r = conn.execute(
                "MATCH (p:papers {paper_id: $id}) "
                "RETURN p.doi, p.journal_ref, p.inspire_id",
                {"id": P_HEP_TH},
            )
            row = r.get_next()
        finally:
            del db
        assert row[0] == "10.1234/CANONICAL", (
            "F1 regression: doi clobbered to NULL by a re-MERGE"
        )
        assert row[1] == "JHEP (2024)", (
            "F1 regression: journal_ref clobbered to NULL"
        )
        assert row[2] == "42", "F1 regression: inspire_id clobbered to NULL"

    def test_f1_inspire_merge_overwrites_with_new_non_null(
        self, populated_db: Path
    ):
        """F1 corollary: COALESCE preserves NULL values, but a re-MERGE
        with a new non-null value still updates (the brief frames this
        as enrichment, not freeze-on-first-write)."""
        first = inspire_ingest._ResolvedInspire(
            inspire_id="42",
            doi="10.1234/OLD",
            journal_ref=None,
            references_arxiv=(),
            arxiv_categories=("hep-th",),
        )
        db = kuzu.Database(str(populated_db))
        try:
            conn = kuzu.Connection(db)
            inspire_ingest._merge_paper_inspire(conn, P_HEP_TH, first)
            # New response has UPDATED doi.
            second = inspire_ingest._ResolvedInspire(
                inspire_id="42",
                doi="10.1234/UPDATED",
                journal_ref="JHEP (2024)",  # also new
                references_arxiv=(),
                arxiv_categories=("hep-th",),
            )
            inspire_ingest._merge_paper_inspire(conn, P_HEP_TH, second)
            r = conn.execute(
                "MATCH (p:papers {paper_id: $id}) RETURN p.doi, p.journal_ref",
                {"id": P_HEP_TH},
            )
            row = r.get_next()
        finally:
            del db
        assert row[0] == "10.1234/UPDATED"
        assert row[1] == "JHEP (2024)"

    @kuzu_reopen_unsupported_on_windows
    def test_f2_enrich_accepts_old_style_hep_th_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
        populated_db: Path,
        checkpoint_path: Path,
    ):
        """F2: ``enrich()`` MUST accept old-style arXiv IDs like
        ``hep-th/9711200`` (Maldacena AdS/CFT). The new-style-only
        ``tools.arxiv_fetch.validate_paper_id`` rejected them; the
        new ``_validate_paper_id_either_style`` accepts both."""
        old_style_id = "hep-th/9711200"
        # Pre-create the node so the citation pass has a target.
        db = kuzu.Database(str(populated_db))
        try:
            conn = kuzu.Connection(db)
            conn.execute(
                "MERGE (p:papers {paper_id: $id}) ON CREATE SET p.title = 'Maldacena'",
                {"id": old_style_id},
            )
        finally:
            del db

        def _stub(arxiv_id: str, contact_email: str) -> dict[str, Any] | None:
            return _record(
                control_number=99999,
                arxiv_categories=["hep-th"],
                refs_arxiv=[],
                doi="10.1016/...",
            )

        monkeypatch.setattr(inspire_ingest, "_fetch_inspire_record", _stub)

        # No ValueError should be raised here.
        inspire_ingest.enrich(
            paper_ids=[old_style_id],
            db_path=populated_db,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )
        # Verify the paper was actually enriched.
        db = kuzu.Database(str(populated_db))
        try:
            conn = kuzu.Connection(db)
            r = conn.execute(
                "MATCH (p:papers {paper_id: $id}) RETURN p.inspire_id",
                {"id": old_style_id},
            )
            row = r.get_next()
        finally:
            del db
        assert row[0] == "99999"

    def test_f2_validator_rejects_truly_invalid_ids(self):
        """F2: the broader validator must STILL reject path-traversal
        attempts (Threat 1) and other malformed strings."""
        for bad in ["../../etc/passwd", "", "not-an-arxiv-id", "no-numeric-part"]:
            with pytest.raises(ValueError):
                inspire_ingest._validate_paper_id_either_style(bad)

    def test_f4_inspire_creates_node_then_emits_edge_to_resolved_paper(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db_path: Path,
        checkpoint_path: Path,
    ):
        """F4: a paper resolved AND merged in Pass 1 must be visible to
        Pass 2's edge-emission filter even when it was NOT in the
        graph at ``enrich()`` start."""
        # Empty graph initially — apply schema only.
        kuzudb_schema.apply_schema(db_path)

        a_id = "2401.20001"
        b_id = "2401.20002"

        def _stub(arxiv_id: str, contact_email: str) -> dict[str, Any] | None:
            corpus = {
                a_id: _record(
                    control_number=10001,
                    arxiv_categories=["hep-th"],
                    refs_arxiv=[b_id],
                ),
                b_id: _record(
                    control_number=10002,
                    arxiv_categories=["hep-th"],
                    refs_arxiv=[],
                ),
            }
            return corpus[arxiv_id]

        monkeypatch.setattr(inspire_ingest, "_fetch_inspire_record", _stub)

        inspire_ingest.enrich(
            paper_ids=[a_id, b_id],
            db_path=db_path,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )

        # The edge a -> b must be present even though both nodes were
        # newly created during this run.
        db = kuzu.Database(str(db_path))
        try:
            conn = kuzu.Connection(db)
            r = conn.execute(
                "MATCH (a:papers {paper_id: $a})-[r:cites]->(b:papers {paper_id: $b}) "
                "RETURN r.source",
                {"a": a_id, "b": b_id},
            )
            assert r.has_next(), (
                "F4 regression: edge to a Pass-1-created node was dropped"
            )
        finally:
            del db

    def test_f5_fetch_inspire_record_validates_paper_id(self):
        """F5: ``_fetch_inspire_record`` validates ``arxiv_id`` before
        any I/O so a future direct caller cannot smuggle malicious
        input. Defense-in-depth for Threat 1."""
        with pytest.raises(ValueError):
            inspire_ingest._fetch_inspire_record(
                "../../etc/passwd", "test@example.com"
            )

    @kuzu_reopen_unsupported_on_windows
    def test_f6_failure_run_flushes_checkpoint_at_batch_size(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db_path: Path,
        checkpoint_path: Path,
    ):
        """F6: a long failure run hits the checkpoint flush cadence so
        a hard kill mid-run does not lose the in-memory failures."""
        import urllib.error

        def _always_fail(arxiv_id: str, contact_email: str) -> dict[str, Any] | None:
            raise urllib.error.URLError(f"simulated failure for {arxiv_id}")

        monkeypatch.setattr(inspire_ingest, "_fetch_inspire_record", _always_fail)
        kuzudb_schema.apply_schema(db_path)

        # Four papers, batch_size=2 — checkpoint MUST be flushed at
        # the boundary (after the second failure).
        ids = ["2401.30001", "2401.30002", "2401.30003", "2401.30004"]
        # Pre-create nodes to satisfy in_corpus.
        db = kuzu.Database(str(db_path))
        try:
            conn = kuzu.Connection(db)
            for i in ids:
                conn.execute(
                    "MERGE (p:papers {paper_id: $id})", {"id": i}
                )
        finally:
            del db

        inspire_ingest.enrich(
            paper_ids=ids,
            db_path=db_path,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
            batch_size=2,
        )

        # All four IDs are in the failures list at end-of-run.
        payload = json.loads(checkpoint_path.read_text())
        failed_ids = {entry["arxiv_id"] for entry in payload["fetch_failures"]}
        assert failed_ids == set(ids)

    @kuzu_reopen_unsupported_on_windows
    def test_f8_arxiv_categories_filter_anchor_for_post_f9(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db_path: Path,
        checkpoint_path: Path,
    ):
        """F8: forward-compat anchor for AC#1.

        When the `papers.categories` column is eventually populated
        with real arXiv categories (post-F9 fix), this test verifies
        ``enrich()`` correctly iterates papers tagged ``hep-th`` /
        ``math-ph``. Today the implementation iterates ALL papers and
        gates on INSPIRE's response; this test pins that the iteration
        path itself doesn't drop a hep-th paper."""
        kuzudb_schema.apply_schema(db_path)
        # Pre-populate a paper with arXiv-style categories (the
        # post-F9 shape).
        hep_id = "2401.40001"
        ag_id = "2401.40002"
        db = kuzu.Database(str(db_path))
        try:
            conn = kuzu.Connection(db)
            conn.execute(
                "MERGE (p:papers {paper_id: $id}) ON CREATE SET p.categories = 'hep-th'",
                {"id": hep_id},
            )
            conn.execute(
                "MERGE (p:papers {paper_id: $id}) ON CREATE SET p.categories = 'math.AG'",
                {"id": ag_id},
            )
        finally:
            del db

        def _stub(arxiv_id: str, contact_email: str) -> dict[str, Any] | None:
            corpus = {
                hep_id: _record(
                    control_number=70001,
                    arxiv_categories=["hep-th"],
                    refs_arxiv=[],
                ),
                ag_id: _record(
                    control_number=70002,
                    arxiv_categories=["math.AG"],
                    refs_arxiv=[],
                ),
            }
            return corpus[arxiv_id]

        monkeypatch.setattr(inspire_ingest, "_fetch_inspire_record", _stub)

        inspire_ingest.enrich(
            paper_ids=[hep_id, ag_id],
            db_path=db_path,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )

        # The hep-th paper IS enriched; the math.AG paper IS NOT
        # (post-fetch physics gate filters it out).
        db = kuzu.Database(str(db_path))
        try:
            conn = kuzu.Connection(db)
            r = conn.execute(
                "MATCH (p:papers {paper_id: $id}) RETURN p.inspire_id",
                {"id": hep_id},
            )
            assert r.get_next()[0] == "70001"
            r = conn.execute(
                "MATCH (p:papers {paper_id: $id}) RETURN p.inspire_id",
                {"id": ag_id},
            )
            assert r.get_next()[0] is None
        finally:
            del db


class TestFFindingInheritance:
    """Tests confirming each closed E09_S01 finding doesn't reopen here."""

    def test_f2_response_cap_tight(self):
        """F2: INSPIRE has its own response cap, less than the 200 MB
        arXiv-tarball cap."""
        from tools.arxiv_fetch import MAX_RESPONSE_BYTES as ARXIV_CAP

        assert inspire_ingest.INSPIRE_MAX_RESPONSE_BYTES <= 16 * 1024 * 1024
        assert inspire_ingest.INSPIRE_MAX_RESPONSE_BYTES < ARXIV_CAP

    @kuzu_reopen_unsupported_on_windows
    def test_f3_fetch_failure_tracked_and_retried(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fixture_corpus: dict[str, dict[str, Any] | None],
        populated_db: Path,
        checkpoint_path: Path,
    ):
        """F3 (mirrored from E09_S01): URLError records into
        state['fetch_failures']; resume retries."""
        import urllib.error

        seen = {"count": 0}

        def _failing_then_succeeding(
            arxiv_id: str, contact_email: str
        ) -> dict[str, Any] | None:
            if arxiv_id == P_HEP_TH and seen["count"] == 0:
                seen["count"] += 1
                raise urllib.error.URLError("simulated DNS failure")
            return fixture_corpus[arxiv_id]

        monkeypatch.setattr(
            inspire_ingest, "_fetch_inspire_record", _failing_then_succeeding
        )

        state1 = inspire_ingest.enrich(
            paper_ids=CORPUS_IDS,
            db_path=populated_db,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )
        failures = {entry["arxiv_id"] for entry in state1["fetch_failures"]}
        assert P_HEP_TH in failures
        assert P_HEP_TH not in state1["resolved"]

        state2 = inspire_ingest.enrich(
            paper_ids=CORPUS_IDS,
            db_path=populated_db,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )
        assert P_HEP_TH in state2["resolved"]
        assert state2["fetch_failures"] == []

    def test_f8_inspire_id_collision_logged(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        populated_db: Path,
        checkpoint_path: Path,
    ):
        """F8 (mirrored): two papers resolving to the same INSPIRE
        record_id must produce a warning."""
        # Same control_number for two distinct arXiv IDs.
        collision_corpus = {
            P_HEP_TH: _record(
                control_number=42,
                arxiv_categories=["hep-th"],
                refs_arxiv=[],
            ),
            P_MATH_PH: _record(
                control_number=42,  # collision!
                arxiv_categories=["math-ph"],
                refs_arxiv=[],
            ),
        }

        def _stub(arxiv_id: str, contact_email: str) -> dict[str, Any] | None:
            return collision_corpus[arxiv_id]

        monkeypatch.setattr(inspire_ingest, "_fetch_inspire_record", _stub)

        with caplog.at_level("WARNING", logger="ingest.inspire_ingest"):
            inspire_ingest.enrich(
                paper_ids=[P_HEP_TH, P_MATH_PH],
                db_path=populated_db,
                checkpoint_path=checkpoint_path,
                contact_email="test@example.com",
                sleep_seconds=0,
            )

        warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert any(
            "inspire_id collision" in w and "42" in w for w in warnings
        ), f"expected inspire_id collision warning, got: {warnings}"

    def test_f6_schema_meta_stamps_v2(self, db_path: Path):
        kuzudb_schema.apply_schema(db_path)
        # The version constant matches the on-disk stamp.
        assert kuzudb_schema.read_schema_version(db_path) == 2

    def test_f10_assertions_are_non_vacuous(self):
        """F10: every assertion must fail when the production behavior is
        wrong. This test sanity-checks that the polite-pool sleep is
        actually below the AC ceiling."""
        # Brief AC#6: ≤ 5 requests/second.
        # Implementation must sleep ≥ 0.2 s between requests (= 5 rps).
        assert inspire_ingest.INSPIRE_POLITE_SLEEP_SECONDS >= 0.2


# ---------------------------------------------------------------------------
# Validation / safety
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_paper_id_rejected_before_any_io(
        self,
        stub_fetcher: list[str],
        populated_db: Path,
        checkpoint_path: Path,
    ):
        """Threat 1: every paper_id is regex-validated before any HTTP /
        DB write. Mirrors E09_S01's test."""
        with pytest.raises(ValueError):
            inspire_ingest.enrich(
                paper_ids=[P_HEP_TH, "../../etc/passwd"],
                db_path=populated_db,
                checkpoint_path=checkpoint_path,
                contact_email="test@example.com",
                sleep_seconds=0,
            )
        assert stub_fetcher == []

    def test_no_live_network_calls_in_test_run(
        self,
        stub_fetcher: list[str],
        populated_db: Path,
        checkpoint_path: Path,
    ):
        """Sanity guard: the live fetcher must be replaced for the entire
        test run."""
        inspire_ingest.enrich(
            paper_ids=CORPUS_IDS,
            db_path=populated_db,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )
        assert set(stub_fetcher) <= set(CORPUS_IDS)
        assert len(stub_fetcher) == len(CORPUS_IDS)


# ---------------------------------------------------------------------------
# Resume idempotency
# ---------------------------------------------------------------------------


class TestResume:
    def test_re_enrich_is_idempotent(
        self,
        stub_fetcher: list[str],
        populated_db: Path,
        checkpoint_path: Path,
    ):
        """Run enrich twice; node + edge counts stable, no extra fetches."""
        inspire_ingest.enrich(
            paper_ids=CORPUS_IDS,
            db_path=populated_db,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )
        before = len(stub_fetcher)
        inspire_ingest.enrich(
            paper_ids=CORPUS_IDS,
            db_path=populated_db,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )
        assert len(stub_fetcher) == before

        db = kuzu.Database(str(populated_db))
        try:
            conn = kuzu.Connection(db)
            edges = conn.execute(
                "MATCH ()-[r:cites {source: 'inspire'}]->() RETURN COUNT(*)"
            ).get_next()[0]
        finally:
            del db
        assert edges == 2

    def test_checkpoint_atomic_write_no_tmp_left_behind(
        self,
        stub_fetcher: list[str],
        populated_db: Path,
        checkpoint_path: Path,
    ):
        inspire_ingest.enrich(
            paper_ids=CORPUS_IDS,
            db_path=populated_db,
            checkpoint_path=checkpoint_path,
            contact_email="test@example.com",
            sleep_seconds=0,
        )
        tmp_sibling = checkpoint_path.with_suffix(checkpoint_path.suffix + ".tmp")
        assert not tmp_sibling.exists()
        payload = json.loads(checkpoint_path.read_text())
        assert set(payload["resolved"].keys()) == set(CORPUS_IDS)


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


class TestCLI:
    def test_include_back_refs_flag_is_not_implemented(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")
        rc = inspire_ingest.main(
            [
                "--checkpoint",
                str(tmp_path / "ck.json"),
                "--kuzudb",
                str(tmp_path / "kuzu"),
                "--include-back-refs",
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
        rc = inspire_ingest.main(
            [
                "--checkpoint",
                str(tmp_path / "ck.json"),
                "--kuzudb",
                str(tmp_path / "kuzu"),
            ]
        )
        assert rc == 2
        captured = capsys.readouterr()
        assert "ARXMCP_CONTACT_EMAIL" in captured.err

    def test_empty_graph_errors_when_no_seed_file(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """When no `--seed-file` is given and the graph has no `papers`
        nodes, the CLI must error rather than silently no-op."""
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")
        rc = inspire_ingest.main(
            [
                "--checkpoint",
                str(tmp_path / "ck.json"),
                "--kuzudb",
                str(tmp_path / "kuzu"),
            ]
        )
        assert rc == 2
        captured = capsys.readouterr()
        assert "no `papers` nodes" in captured.err

    def test_seed_file_path_constrains_enrichment(
        self,
        stub_fetcher: list[str],
        monkeypatch: pytest.MonkeyPatch,
        populated_db: Path,
        tmp_path: Path,
    ):
        """`--seed-file` provides a constrained list rather than scanning
        the graph."""
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")
        seed_file = tmp_path / "subset.txt"
        seed_file.write_text(f"{P_HEP_TH}\n", encoding="utf-8")
        rc = inspire_ingest.main(
            [
                "--seed-file",
                str(seed_file),
                "--checkpoint",
                str(tmp_path / "ck.json"),
                "--kuzudb",
                str(populated_db),
            ]
        )
        assert rc == 0
        # Only the one paper from the seed file was fetched.
        assert stub_fetcher == [P_HEP_TH]
