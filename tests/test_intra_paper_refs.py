"""Unit tests for E09_S03 — intra-paper ``\\ref{}`` ingest pass.

Mirrors the discipline of ``tests/test_graph_ingest.py`` and
``tests/test_inspire_ingest.py``: real Kùzu DB in ``tmp_path``,
synthetic LaTeXML HTML written to per-paper directories, real (tiny)
LanceDB chunks table for the theorem-label resolution pass.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import kuzu
import pyarrow as pa
import pytest

from ingest import kuzudb_schema
from ingest.intra_paper_refs import (
    _extract_intrapaper_labels,
    _resolved_labels_for_paper,
    ingest,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

P_HAS_REFS = "2401.60001"
P_NO_REFS = "2401.60002"
P_MISSING_HTML = "2401.60003"

# Sample LaTeXML output snippets
HTML_WITH_REFS = """<!DOCTYPE html>
<html><body>
<section>
  <p>See <a class="ltx_ref" href="#thm-main" title="Theorem 1">Theorem 1</a>
  and <a class="ltx_ref" href="#lem-aux">Lemma 2</a>. We also reference
  the bibliography in <a class="ltx_ref ltx_bibref" href="#bib1">[1]</a>
  but that's not an intra-paper theorem ref.</p>
  <p>An external link: <a class="ltx_ref" href="http://example.com">ext</a>.</p>
  <p>A duplicate: <a class="ltx_ref" href="#thm-main">Theorem 1 again</a>.</p>
</section>
</body></html>
"""

HTML_NO_REFS = """<!DOCTYPE html>
<html><body><p>No references in this paper.</p></body></html>
"""


@pytest.fixture
def parsed_dir(tmp_path: Path) -> Path:
    """Pre-populate parsed HTML for the synthetic corpus."""
    root = tmp_path / "parsed"
    (root / P_HAS_REFS).mkdir(parents=True, exist_ok=True)
    (root / P_HAS_REFS / "index.html").write_text(HTML_WITH_REFS, encoding="utf-8")
    (root / P_NO_REFS).mkdir(parents=True, exist_ok=True)
    (root / P_NO_REFS / "index.html").write_text(HTML_NO_REFS, encoding="utf-8")
    # P_MISSING_HTML intentionally absent.
    return root


@pytest.fixture
def lancedb_with_labels(tmp_path: Path) -> Path:
    """Materialize a tiny LanceDB chunks table with theorem_label values
    for the synthetic corpus.

    Two chunks for ``P_HAS_REFS`` carry valid theorem_labels matching
    the HTML's ``\\ref{}`` hrefs:
        - chunk 1: theorem_label="thm-main"
        - chunk 2: theorem_label="lem-aux"
    The ``bib1`` href intentionally does NOT have a matching chunk —
    the test verifies it's filtered out.
    """
    import lancedb

    from ingest.schema import CHUNKS_SCHEMA_V1

    lancedb_path = tmp_path / "lancedb"
    db = lancedb.connect(str(lancedb_path))
    schema = CHUNKS_SCHEMA_V1

    # Build a minimal Arrow table; required columns get placeholder
    # values, nullable columns are populated only where the test
    # actually reads them (theorem_label).
    placeholder_required: dict[str, Any] = {
        "section_path": [],
        "body_text": "",
        "body_tokens": "",
        "chunker_version": "test",
        "embedder_version": "test",
    }
    rows = [
        {
            "chunk_id": f"arxiv:{P_HAS_REFS}:0000000000000001",
            "paper_id": P_HAS_REFS,
            "kind": "stmt",
            "theorem_label": "thm-main",
            **placeholder_required,
        },
        {
            "chunk_id": f"arxiv:{P_HAS_REFS}:0000000000000002",
            "paper_id": P_HAS_REFS,
            "kind": "lemma",
            "theorem_label": "lem-aux",
            **placeholder_required,
        },
        {
            "chunk_id": f"arxiv:{P_NO_REFS}:0000000000000003",
            "paper_id": P_NO_REFS,
            "kind": "stmt",
            "theorem_label": None,
            **placeholder_required,
        },
    ]
    payload: dict[str, list[Any]] = {field.name: [] for field in schema}
    for row in rows:
        for field in schema:
            payload[field.name].append(row.get(field.name))
    table = pa.Table.from_pydict(payload, schema=schema)
    db.create_table("chunks", data=table, mode="create")
    return lancedb_path


@pytest.fixture
def kuzu_db(tmp_path: Path) -> Path:
    """Materialize an empty Kùzu DB with v2 schema."""
    db_path = tmp_path / "kuzu_test"
    kuzudb_schema.apply_schema(db_path)
    db = kuzu.Database(str(db_path))
    try:
        conn = kuzu.Connection(db)
        for pid in (P_HAS_REFS, P_NO_REFS, P_MISSING_HTML):
            conn.execute(
                "MERGE (p:papers {paper_id: $id}) ON CREATE SET p.title = $t",
                {"id": pid, "t": f"Title-{pid}"},
            )
    finally:
        del db
    return db_path


@pytest.fixture
def checkpoint_path(tmp_path: Path) -> Path:
    return tmp_path / "ops" / "intra-refs-checkpoint.json"


# ---------------------------------------------------------------------------
# HTML extractor
# ---------------------------------------------------------------------------


class TestExtractor:
    def test_extracts_intra_paper_anchor_hrefs(self):
        labels = _extract_intrapaper_labels(HTML_WITH_REFS)
        # bib1 IS extracted (it's still a #-prefixed local href even
        # though it points to a bibliography entry). The downstream
        # filter (LanceDB theorem_label match) drops it because no
        # chunk has theorem_label='bib1'.
        assert "thm-main" in labels
        assert "lem-aux" in labels
        # F9 fix from the E09_S03 critique: the fixture's bib1 anchor
        # carries ``class="ltx_ref ltx_bibref"`` (LaTeXML's
        # \\cite{} rendering); the post-fix extractor filters it out
        # so ``raw_ref_count`` reflects theorem refs only.
        assert "bib1" not in labels

    def test_excludes_external_links(self):
        labels = _extract_intrapaper_labels(HTML_WITH_REFS)
        assert not any(label.startswith("http") for label in labels)

    def test_dedupes_duplicate_refs(self):
        labels = _extract_intrapaper_labels(HTML_WITH_REFS)
        # The ``thm-main`` href appears TWICE in the source; the
        # extractor returns a set, so it appears once.
        assert sum(1 for label in labels if label == "thm-main") == 1

    def test_empty_html_returns_empty_set(self):
        assert _extract_intrapaper_labels("<html></html>") == set()
        assert _extract_intrapaper_labels(HTML_NO_REFS) == set()

    def test_f9_excludes_ltx_bibref_class(self):
        """F9 fix from the E09_S03 critique: anchors with ``class``
        containing ``ltx_bibref`` are LaTeXML's ``\\cite{}`` rendering
        and must NOT be conflated with theorem refs."""
        html = """<html><body>
        <a class="ltx_ref ltx_bibref" href="#cite-foo">[Foo+24]</a>
        <a class="ltx_ref" href="#thm-1">Theorem 1</a>
        </body></html>"""
        labels = _extract_intrapaper_labels(html)
        assert "thm-1" in labels
        assert "cite-foo" not in labels


# ---------------------------------------------------------------------------
# LanceDB resolved-label lookup
# ---------------------------------------------------------------------------


class TestResolvedLabels:
    def test_returns_only_chunk_backed_labels(
        self, lancedb_with_labels: Path
    ):
        # F6: helper now takes an OPEN chunks_table handle, not a path.
        from ingest.intra_paper_refs import _open_chunks_table_or_none

        table = _open_chunks_table_or_none(lancedb_with_labels)
        candidates = {"thm-main", "lem-aux", "bib1"}
        resolved = _resolved_labels_for_paper(P_HAS_REFS, candidates, table)
        assert resolved == {"thm-main", "lem-aux"}

    def test_empty_candidate_set_returns_empty(self, lancedb_with_labels: Path):
        from ingest.intra_paper_refs import _open_chunks_table_or_none

        table = _open_chunks_table_or_none(lancedb_with_labels)
        resolved = _resolved_labels_for_paper(P_HAS_REFS, set(), table)
        assert resolved == set()

    def test_none_chunks_table_returns_empty(self):
        # F6: passing None (no LanceDB available) returns empty.
        resolved = _resolved_labels_for_paper(P_HAS_REFS, {"thm-main"}, None)
        assert resolved == set()

    def test_open_chunks_table_or_none_handles_missing_path(self, tmp_path: Path):
        from ingest.intra_paper_refs import _open_chunks_table_or_none

        assert _open_chunks_table_or_none(tmp_path / "no-such-lancedb") is None


# ---------------------------------------------------------------------------
# Full ingest happy path
# ---------------------------------------------------------------------------


class TestIngest:
    def test_emits_self_edge_for_paper_with_resolved_refs(
        self,
        parsed_dir: Path,
        lancedb_with_labels: Path,
        kuzu_db: Path,
        checkpoint_path: Path,
    ):
        ingest(
            paper_ids=[P_HAS_REFS, P_NO_REFS],
            db_path=kuzu_db,
            parsed_dir=parsed_dir,
            lancedb_path=lancedb_with_labels,
            checkpoint_path=checkpoint_path,
        )
        db = kuzu.Database(str(kuzu_db))
        try:
            conn = kuzu.Connection(db)
            r = conn.execute(
                "MATCH (a:papers)-[r:cites {source: 'intra-paper'}]->(b:papers) "
                "RETURN a.paper_id, b.paper_id, r.confidence "
                "ORDER BY a.paper_id"
            )
            edges = []
            while r.has_next():
                edges.append(tuple(r.get_next()))
        finally:
            del db
        # Exactly one self-edge: P_HAS_REFS -> P_HAS_REFS.
        assert edges == [(P_HAS_REFS, P_HAS_REFS, pytest.approx(1.0))]

    def test_paper_without_refs_emits_no_edge(
        self,
        parsed_dir: Path,
        lancedb_with_labels: Path,
        kuzu_db: Path,
        checkpoint_path: Path,
    ):
        ingest(
            paper_ids=[P_NO_REFS],
            db_path=kuzu_db,
            parsed_dir=parsed_dir,
            lancedb_path=lancedb_with_labels,
            checkpoint_path=checkpoint_path,
        )
        db = kuzu.Database(str(kuzu_db))
        try:
            conn = kuzu.Connection(db)
            count = conn.execute(
                "MATCH (a:papers)-[r:cites {source: 'intra-paper'}]->(b:papers) "
                "RETURN COUNT(*)"
            ).get_next()[0]
        finally:
            del db
        assert count == 0

    def test_missing_html_recorded_as_parse_failure(
        self,
        parsed_dir: Path,
        lancedb_with_labels: Path,
        kuzu_db: Path,
        checkpoint_path: Path,
    ):
        state = ingest(
            paper_ids=[P_MISSING_HTML],
            db_path=kuzu_db,
            parsed_dir=parsed_dir,
            lancedb_path=lancedb_with_labels,
            checkpoint_path=checkpoint_path,
        )
        failures = {entry["paper_id"] for entry in state["parse_failures"]}
        assert P_MISSING_HTML in failures

    def test_idempotent_re_run(
        self,
        parsed_dir: Path,
        lancedb_with_labels: Path,
        kuzu_db: Path,
        checkpoint_path: Path,
    ):
        ingest(
            paper_ids=[P_HAS_REFS, P_NO_REFS],
            db_path=kuzu_db,
            parsed_dir=parsed_dir,
            lancedb_path=lancedb_with_labels,
            checkpoint_path=checkpoint_path,
        )
        ingest(
            paper_ids=[P_HAS_REFS, P_NO_REFS],
            db_path=kuzu_db,
            parsed_dir=parsed_dir,
            lancedb_path=lancedb_with_labels,
            checkpoint_path=checkpoint_path,
        )
        db = kuzu.Database(str(kuzu_db))
        try:
            conn = kuzu.Connection(db)
            count = conn.execute(
                "MATCH (a:papers)-[r:cites {source: 'intra-paper'}]->(b:papers) "
                "RETURN COUNT(*)"
            ).get_next()[0]
        finally:
            del db
        # Exactly one edge survives — MERGE upsert is idempotent.
        assert count == 1

    def test_invalid_paper_id_rejected_before_io(
        self,
        parsed_dir: Path,
        lancedb_with_labels: Path,
        kuzu_db: Path,
        checkpoint_path: Path,
    ):
        with pytest.raises(ValueError):
            ingest(
                paper_ids=[P_HAS_REFS, "../../etc/passwd"],
                db_path=kuzu_db,
                parsed_dir=parsed_dir,
                lancedb_path=lancedb_with_labels,
                checkpoint_path=checkpoint_path,
            )

    def test_atomic_checkpoint_no_tmp_left_behind(
        self,
        parsed_dir: Path,
        lancedb_with_labels: Path,
        kuzu_db: Path,
        checkpoint_path: Path,
    ):
        ingest(
            paper_ids=[P_HAS_REFS],
            db_path=kuzu_db,
            parsed_dir=parsed_dir,
            lancedb_path=lancedb_with_labels,
            checkpoint_path=checkpoint_path,
        )
        tmp_sibling = checkpoint_path.with_suffix(checkpoint_path.suffix + ".tmp")
        assert not tmp_sibling.exists()
        payload = json.loads(checkpoint_path.read_text())
        assert P_HAS_REFS in payload["edges_added"]
        assert P_HAS_REFS in payload["processed"]
