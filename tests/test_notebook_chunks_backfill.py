"""Tests for ``tools.notebook_chunks_backfill`` (source-truth-m2).

Mirrors ``tests/test_notebook_documents_backfill.py`` in shape: an offline
build of a real per-notebook chunks table (via the real chunker + synthetic
embeddings + ``write_chunks``), a per-notebook ``documents.db`` registry, and
assertions that the five chunks-schema-v2 columns are hydrated with

- ``truncated`` / ``printed_number`` from the chunk-id-matched re-chunk,
- ``source_revision_id`` / ``license_ref`` from the registry join,
- a byte-stable ``source_span`` JSON string whose ``txt`` is the authoritative
  NFC-normalized-body-text hash,

that the embedding columns are BYTE-IDENTICAL pre/post (the 0-re-embed
guarantee), that abstentions (chunk-id miss, registry miss, multi-row registry)
are counted + reason-coded in the report, that the F2 sanity flag fires, that a
re-run is idempotent, and — the STRUCTURAL 0-re-embed guarantee — that the
driver imports no embedder / store.

All offline: notebooks + parsed corpus live under ``tmp_path``, preamble
resolution is a hermetic ``lambda: None`` seam, and no network is touched.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import unicodedata
from pathlib import Path
from unittest.mock import patch

import lancedb
import numpy as np
import pytest

from ingest.chunker import chunk_paper
from ingest.chunker_types import ChunkRecord
from ingest.embedder import EMBEDDER_VERSION, EMBEDDING_DIM
from ingest.schema import EmbedRecord
from ingest.store import write_chunks
from server.documents_store import (
    DOCUMENTS_DB_FILENAME,
    DocumentRecord,
    DocumentsStore,
)
from tools import notebook_chunks_backfill as backfill

SLUG = "bridgeland-stability"

# A well-formed 64-hex parse-artifact checksum used across the registry
# fixtures so the source_span ``rev`` (its 16-hex prefix) is deterministic.
PARSE_SHA = "ab12cd34ef56ab78cd90ef12ab34cd56ef78ab90cd12ef34ab56cd78ef90ab12"

# A parsed HTML fixture: one numbered theorem + its proof + a section prose
# paragraph. Re-chunking reproduces these three chunk_ids exactly.
PAPER = "2312.00001"
HTML = """<!DOCTYPE html><html><body>
<article class="ltx_document">
  <section class="ltx_section" id="S1">
    <h2 class="ltx_title ltx_title_section">1. Main</h2>
    <p class="ltx_p">This is a stand-alone section prose paragraph with more than
    eighty characters so the section chunk is emitted for the backfill to see.</p>
    <div id="S1.Thmtheorem1" class="ltx_theorem ltx_theorem_theorem">
      <h6 class="ltx_title ltx_runin ltx_title_theorem">
        <span class="ltx_tag ltx_tag_theorem">Theorem 1.1</span> (Key).</h6>
      <div class="ltx_para"><p class="ltx_p">The statement of the key theorem is
      given here in full detail for the backfill round-trip test.</p></div>
    </div>
    <div class="ltx_proof">
      <div class="ltx_para"><p class="ltx_p">The proof of the key theorem proceeds
      by a direct and careful argument spelled out in this window.</p></div>
    </div>
  </section>
</article>
</body></html>"""

# An old-style, section-less, theorem-less render that mentions theorem keywords
# in prose >= the F2 threshold — a likely total markup-path miss (spike-2 F2).
F2_PAPER = "hep-th/9901001"
F2_HTML = """<!DOCTYPE html><html><body>
<article class="ltx_document">
  <div class="ltx_para"><p class="ltx_p">In this note we recall a theorem of the
  first kind, then a second theorem, then a lemma, and finally a proposition,
  all stated inline in prose with no markup environments whatsoever, which is
  exactly the shape that defeats the theorem-tag extractor.</p></div>
</article>
</body></html>"""


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _synth_embeddings(chunks: list[ChunkRecord], *, seed: int = 0) -> EmbedRecord:
    """Random L2-normalized vectors routed by ``kind == "proof"``."""
    rng = np.random.default_rng(seed)
    ids_stmt: list[str] = []
    ids_proof: list[str] = []
    rows_stmt: list[np.ndarray] = []
    rows_proof: list[np.ndarray] = []
    for c in chunks:
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        if c.kind == "proof":
            ids_proof.append(c.chunk_id)
            rows_proof.append(v)
        else:
            ids_stmt.append(c.chunk_id)
            rows_stmt.append(v)
    emb_stmt = (
        np.stack(rows_stmt) if rows_stmt else np.zeros((0, EMBEDDING_DIM), np.float32)
    )
    emb_proof = (
        np.stack(rows_proof) if rows_proof else np.zeros((0, EMBEDDING_DIM), np.float32)
    )
    return EmbedRecord(
        chunk_ids_stmt=ids_stmt,
        embedding_stmt=emb_stmt,
        chunk_ids_proof=ids_proof,
        embedding_proof=emb_proof,
        embedder_version=EMBEDDER_VERSION,
    )


def _parsed_root(tmp_path: Path, papers: dict[str, str]) -> Path:
    parsed = tmp_path / "parsed"
    for pid, html in papers.items():
        d = parsed / pid
        d.mkdir(parents=True)
        (d / "index.html").write_text(html, encoding="utf-8")
    return parsed


def _lancedb_dir(base: Path) -> Path:
    return base / SLUG / "lancedb"


def _build_table_from_html(
    tmp_path: Path,
    base: Path,
    parsed_root: Path,
    paper_id: str,
    *,
    seed: int = 1,
) -> list[ChunkRecord]:
    """Chunk a parsed fixture (hermetic empty preamble) + synthetic embeddings
    + write_chunks into the notebook's lancedb, returning the real records."""
    with (
        patch("ingest.chunker.PARSED_DIR", parsed_root),
        patch("ingest.chunker.CHUNKS_DIR", tmp_path / "chunks_out"),
        patch("ingest.chunker._resolve_preamble_doc", lambda _pid: None),
    ):
        records = chunk_paper(paper_id)
    assert records, "fixture must produce at least one chunk"
    write_chunks(records, _synth_embeddings(records, seed=seed), lancedb_path=_lancedb_dir(base))
    return records


def _make_fixed_chunk(paper_id: str, kind: str, body: str, suffix: str) -> ChunkRecord:
    """A ChunkRecord with a FIXED (non-content-addressed) chunk_id, used to
    fabricate rows the re-chunk will NOT reproduce (a MISS)."""
    return ChunkRecord(
        chunk_id=f"arxiv:{paper_id}:{suffix}",
        paper_id=paper_id,
        kind=kind,
        section_path=[],
        theorem_name=None,
        theorem_label=None,
        body_text=body,
        body_tokens=" ".join(body.split()).lower() or "tok",
        preamble_ref=None,
    )


def _register(base: Path, records: list[DocumentRecord]) -> None:
    db_path = base / SLUG / DOCUMENTS_DB_FILENAME

    async def _go() -> None:
        store = await DocumentsStore.open(db_path)
        try:
            await store.upsert_records(records)
        finally:
            await store.close()

    asyncio.run(_go())


def _doc(work_id: str, *, version: str = "", license_status: str = "eligible") -> DocumentRecord:
    return DocumentRecord(
        work_id=work_id,
        arxiv_version=version,
        raw_source_sha256=None,
        raw_source_status="unavailable",
        parse_artifact_sha256=PARSE_SHA,
        chunker_version="v1.1",
        parser_used=None,
        latexml_version=None,
        fetched_at="2026-07-13T00:00:00Z",
        license_uri=None,
        license_status=license_status,
        status="active",
    )


def _read_rows(base: Path) -> dict[str, dict]:
    db = lancedb.connect(str(_lancedb_dir(base)))
    tbl = db.open_table("chunks")
    return {r["chunk_id"]: r for r in tbl.to_arrow().to_pylist()}


def _run(base: Path, parsed_root: Path) -> int:
    """Run the backfill with the hermetic empty-preamble seam."""
    return backfill.run(
        SLUG,
        base=base,
        corpus_parsed_dir=parsed_root,
        resolve_preamble=lambda _pid: None,
    )


# ---------------------------------------------------------------------------
# Pure-helper unit tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_revision_id_bare_and_versioned(self):
        assert backfill._revision_id(_doc("math/0212237")) == "math/0212237"
        assert backfill._revision_id(_doc("2312.00001", version="v2")) == "2312.00001@v2"

    def test_normalized_text_hash_is_nfc_ws_collapsed(self):
        body = "  A   é  statement \n with  spaces  "
        expected = hashlib.sha256(
            unicodedata.normalize("NFC", " ".join(body.split())).encode("utf-8")
        ).hexdigest()
        assert backfill._normalized_text_hash(body) == expected
        assert len(expected) == 64
        # NFC: precomposed é and decomposed e+U+0301 hash identically.
        assert backfill._normalized_text_hash("é") == backfill._normalized_text_hash("é")

    def test_source_span_json_shape_and_byte_stability(self):
        s = backfill._source_span_json("ab12cd34ef56ab78", "the body text")
        obj = json.loads(s)
        assert set(obj) == {"id", "rev", "txt"}
        assert obj["rev"] == "ab12cd34ef56ab78"
        assert obj["id"] == ""
        assert obj["txt"] == backfill._normalized_text_hash("the body text")
        # Byte-stable: sorted keys, no spaces.
        assert s == backfill._source_span_json("ab12cd34ef56ab78", "the body text")
        assert ", " not in s and '": "' not in s

    def test_truncated_fallback_proof_always_false(self):
        # proof short-circuits before counting tokens (huge count ignored).
        fb = backfill._truncated_fallback
        assert fb("proof", "x" * 100, count_tokens=lambda _t: 10**9) is False

    def test_truncated_fallback_stmt_thresholds(self):
        from ingest.chunker import STMT_MAX_TOKENS

        fb = backfill._truncated_fallback
        assert fb("stmt", "short", count_tokens=lambda _t: 5) is False
        assert fb("stmt", "long", count_tokens=lambda _t: STMT_MAX_TOKENS) is True
        assert fb("lemma", "long", count_tokens=lambda _t: STMT_MAX_TOKENS + 1) is True


# ---------------------------------------------------------------------------
# The STRUCTURAL 0-re-embed guarantee
# ---------------------------------------------------------------------------


class TestZeroReEmbed:
    def test_driver_imports_no_embedder_or_store(self):
        source = inspect.getsource(backfill)
        import_block = "\n".join(
            line for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        )
        assert "ingest.store" not in import_block
        assert "ingest.embedder" not in import_block
        assert "write_chunks" not in source
        # It DOES connect to LanceDB directly (the intended mechanism).
        assert "import lancedb" in import_block

    def test_embeddings_bit_identical_pre_post(self, tmp_path):
        base = tmp_path / "notebooks"
        parsed = _parsed_root(tmp_path, {PAPER: HTML})
        _build_table_from_html(tmp_path, base, parsed, PAPER, seed=3)
        _register(base, [_doc(PAPER)])

        before = _read_rows(base)
        assert _run(base, parsed) == 0
        after = _read_rows(base)

        assert set(before) == set(after), "row set (chunk_ids) must be unchanged"
        assert len(after) == len(before)
        for cid, arow in after.items():
            for col in ("embedding_stmt", "embedding_proof"):
                b = before[cid][col]
                a = arow[col]
                if b is None:
                    assert a is None, f"{col} for {cid} changed None->value"
                else:
                    assert np.array_equal(
                        np.asarray(b, dtype=np.float32), np.asarray(a, dtype=np.float32)
                    ), f"{col} for {cid} was mutated by the backfill"


# ---------------------------------------------------------------------------
# HIT path — all five columns hydrated
# ---------------------------------------------------------------------------


class TestHitPath:
    def test_all_five_columns_hydrated(self, tmp_path):
        base = tmp_path / "notebooks"
        parsed = _parsed_root(tmp_path, {PAPER: HTML})
        _build_table_from_html(tmp_path, base, parsed, PAPER, seed=4)
        _register(base, [_doc(PAPER, license_status="eligible")])

        assert _run(base, parsed) == 0
        rows = _read_rows(base)
        assert len(rows) == 3  # stmt + proof + section

        for row in rows.values():
            # Registry-derived: identical on every row of the paper.
            assert row["source_revision_id"] == PAPER
            assert row["license_ref"] == "eligible"
            # truncated is a real bool (never null).
            assert row["truncated"] in (True, False)
            # source_span is a resolved JSON string (HIT + resolved revision).
            span = json.loads(row["source_span"])
            assert span["rev"] == PARSE_SHA[:16]
            assert span["id"] == ""
            assert span["txt"] == backfill._normalized_text_hash(row["body_text"])

        # printed_number: the theorem (stmt) + its paired proof carry "1.1";
        # the section chunk carries None.
        by_kind = {}
        for row in rows.values():
            by_kind.setdefault(row["kind"], []).append(row)
        assert by_kind["stmt"][0]["printed_number"] == "1.1"
        assert by_kind["proof"][0]["printed_number"] == "1.1"
        assert by_kind["section"][0]["printed_number"] is None

    def test_report_tokens_on_full_hit(self, tmp_path, capsys):
        base = tmp_path / "notebooks"
        parsed = _parsed_root(tmp_path, {PAPER: HTML})
        _build_table_from_html(tmp_path, base, parsed, PAPER, seed=5)
        _register(base, [_doc(PAPER)])

        assert _run(base, parsed) == 0
        out = capsys.readouterr().out
        tokens = out.split()
        assert f"slug={SLUG}" in tokens
        assert "rows=3" in tokens
        assert "papers=1" in tokens
        assert "patched=3" in tokens
        assert "resolved=3" in tokens  # source_span resolved=3 (all HIT)
        assert "null=0" in tokens
        # printed_number: 2 numbered (stmt+proof), 1 not_attempted (section).
        assert "numbered=2" in tokens
        assert "not_attempted=1" in tokens


# ---------------------------------------------------------------------------
# Abstention paths + reason codes
# ---------------------------------------------------------------------------


class TestAbstention:
    def test_chunk_id_not_reproduced_miss(self, tmp_path, capsys):
        """Fabricated chunk_ids over a real (but different) parsed HTML -> a
        chunk_id_not_reproduced MISS: source_span/printed_number null,
        truncated via fallback, registry still joined."""
        base = tmp_path / "notebooks"
        parsed = _parsed_root(tmp_path, {PAPER: HTML})
        # Table rows carry FIXED ids the re-chunk will never emit.
        chunks = [
            _make_fixed_chunk(PAPER, "stmt", "fabricated statement body", "1" * 16),
            _make_fixed_chunk(PAPER, "proof", "fabricated proof body", "2" * 16),
        ]
        write_chunks(chunks, _synth_embeddings(chunks, seed=6), lancedb_path=_lancedb_dir(base))
        _register(base, [_doc(PAPER, license_status="not-allowlisted-open")])

        assert _run(base, parsed) == 0
        rows = _read_rows(base)
        for row in rows.values():
            # Revision/license still join (independent of the HTML match).
            assert row["source_revision_id"] == PAPER
            assert row["license_ref"] == "not-allowlisted-open"
            # But the span + printed_number abstain.
            assert row["source_span"] is None
            assert row["printed_number"] is None
        # truncated fallback: proof -> False; stmt(short) -> False.
        assert all(row["truncated"] is False for row in rows.values())

        tokens = capsys.readouterr().out.split()
        assert "chunk_id_not_reproduced=2" in tokens
        assert "resolved=0" in tokens  # source_span resolved=0

    def test_html_missing_miss(self, tmp_path, capsys):
        base = tmp_path / "notebooks"
        parsed = _parsed_root(tmp_path, {})  # no parsed HTML at all
        chunks = [_make_fixed_chunk(PAPER, "stmt", "body", "3" * 16)]
        write_chunks(chunks, _synth_embeddings(chunks, seed=7), lancedb_path=_lancedb_dir(base))
        _register(base, [_doc(PAPER)])

        assert _run(base, parsed) == 0
        tokens = capsys.readouterr().out.split()
        assert "html_missing=1" in tokens

    def test_registry_missing_abstains(self, tmp_path, capsys):
        """No documents.db -> source_revision_id/license_ref null, source_span
        null with reason no_source_revision. truncated/printed_number still
        computed from the (HIT) re-chunk."""
        base = tmp_path / "notebooks"
        parsed = _parsed_root(tmp_path, {PAPER: HTML})
        _build_table_from_html(tmp_path, base, parsed, PAPER, seed=8)
        # deliberately NO _register(...)

        assert _run(base, parsed) == 0
        rows = _read_rows(base)
        for row in rows.values():
            assert row["source_revision_id"] is None
            assert row["license_ref"] is None
            assert row["source_span"] is None
            assert row["truncated"] in (True, False)  # still hydrated (never null)
        # HIT re-chunk still sets printed_number on the theorem-like chunks.
        by_kind = {r["kind"]: r for r in rows.values()}
        assert by_kind["stmt"]["printed_number"] == "1.1"

        tokens = capsys.readouterr().out.split()
        assert "no_source_revision=3" in tokens
        assert "registry_missing=3" in tokens

    def test_ambiguous_multi_row_registry_abstains(self, tmp_path, capsys):
        base = tmp_path / "notebooks"
        parsed = _parsed_root(tmp_path, {PAPER: HTML})
        _build_table_from_html(tmp_path, base, parsed, PAPER, seed=9)
        # Two registry revisions for the same work_id -> defensive abstention.
        _register(base, [_doc(PAPER, version="v1"), _doc(PAPER, version="v2")])

        assert _run(base, parsed) == 0
        rows = _read_rows(base)
        for row in rows.values():
            assert row["source_revision_id"] is None
            assert row["source_span"] is None
        tokens = capsys.readouterr().out.split()
        assert "ambiguous_multi_row=3" in tokens

    def test_f2_suspected_paper_flagged(self, tmp_path, capsys):
        base = tmp_path / "notebooks"
        parsed = _parsed_root(tmp_path, {F2_PAPER: F2_HTML})
        _build_table_from_html(tmp_path, base, parsed, F2_PAPER, seed=10)
        _register(base, [_doc(F2_PAPER)])

        assert _run(base, parsed) == 0
        out = capsys.readouterr().out
        assert F2_PAPER in out
        # count=1 f2 suspected.
        assert "count=1" in out.split()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_rerun_skips_and_preserves(self, tmp_path, capsys):
        base = tmp_path / "notebooks"
        parsed = _parsed_root(tmp_path, {PAPER: HTML})
        _build_table_from_html(tmp_path, base, parsed, PAPER, seed=11)
        _register(base, [_doc(PAPER)])

        assert _run(base, parsed) == 0
        first = _read_rows(base)
        capsys.readouterr()

        assert _run(base, parsed) == 0
        tokens = capsys.readouterr().out.split()
        # Second run: the paper is already hydrated -> skipped, nothing patched.
        assert "patched=0" in tokens
        assert "skipped_papers=1" in tokens
        assert "skipped_rows=3" in tokens

        second = _read_rows(base)
        for cid in first:
            for col in (
                "source_revision_id",
                "source_span",
                "truncated",
                "printed_number",
                "license_ref",
                "embedding_stmt",
                "embedding_proof",
            ):
                b, a = first[cid][col], second[cid][col]
                if isinstance(b, list):
                    assert np.array_equal(np.asarray(b), np.asarray(a))
                else:
                    assert a == b, f"{col} changed on idempotent re-run"


# ---------------------------------------------------------------------------
# Hard errors
# ---------------------------------------------------------------------------


class TestHardErrors:
    def test_missing_chunks_table_raises(self, tmp_path):
        base = tmp_path / "notebooks"
        (base / SLUG).mkdir(parents=True)  # notebook dir but no lancedb table
        from tools._notebook_common import NotebookError

        with pytest.raises(NotebookError, match="no 'chunks'"):
            backfill.run(SLUG, base=base, corpus_parsed_dir=tmp_path / "parsed")

    def test_main_returns_1_on_notebook_error(self, monkeypatch, capsys):
        """``main`` translates a NotebookError (bad slug, no table) into exit 1
        with a message on stderr, never a traceback."""
        from tools._notebook_common import NotebookError

        def _raise(_slug):
            raise NotebookError("boom")

        monkeypatch.setattr(backfill, "run", _raise)
        assert backfill.main([SLUG]) == 1
        assert "error:" in capsys.readouterr().err
