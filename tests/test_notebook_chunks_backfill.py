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
import pyarrow as pa
import pytest

from ingest.chunker import chunk_paper
from ingest.chunker_types import ChunkRecord
from ingest.embedder import EMBEDDER_VERSION, EMBEDDING_DIM
from ingest.preamble_types import PreambleDoc
from ingest.schema import CHUNKS_SCHEMA_V1, EmbedRecord
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
    resolve_preamble=None,
) -> list[ChunkRecord]:
    """Chunk a parsed fixture + synthetic embeddings + write_chunks into the
    notebook's lancedb, returning the real records.

    ``resolve_preamble`` defaults to the hermetic empty-preamble seam
    (``lambda _pid: None``); pass a resolver returning a non-empty
    ``PreambleDoc`` to build the table THROUGH a real preamble so the stored
    chunk_ids are ``hash(preamble_text + body_text)`` (M1 / M4)."""
    if resolve_preamble is None:
        resolve_preamble = lambda _pid: None  # noqa: E731
    with (
        patch("ingest.chunker.PARSED_DIR", parsed_root),
        patch("ingest.chunker.CHUNKS_DIR", tmp_path / "chunks_out"),
        patch("ingest.chunker._resolve_preamble_doc", resolve_preamble),
    ):
        records = chunk_paper(paper_id)
    assert records, "fixture must produce at least one chunk"
    write_chunks(records, _synth_embeddings(records, seed=seed), lancedb_path=_lancedb_dir(base))
    return records


def _nonempty_preamble(paper_id: str) -> PreambleDoc:
    """A ``PreambleDoc`` with a stable NON-empty ``preamble_text`` — drives the
    ``preamble_doc is not None`` branch of ``_rechunk_paper`` that the
    ``lambda _pid: None`` seam never exercises, and (M4) a chunk_id namespace
    distinct from the empty-preamble build."""
    text = "\\newcommand{\\R}{\\mathbb{R}}\n\\newcommand{\\Z}{\\mathbb{Z}}"
    return PreambleDoc(
        paper_id=paper_id,
        source_hash="0" * 64,
        macros=["\\newcommand{\\R}{\\mathbb{R}}", "\\newcommand{\\Z}{\\mathbb{Z}}"],
        preamble_text=text,
        preamble_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
    )


def _patch(base: Path, parsed_root: Path, *, resolve_preamble=None):
    """Call ``backfill._patch_notebook`` directly (returns the ``_NotebookReport``
    object) using the same path derivation ``run`` uses, so a test can assert on
    report internals (``columns_added``, reason-code counts) rather than only the
    printed report."""
    if resolve_preamble is None:
        resolve_preamble = lambda _pid: None  # noqa: E731
    return backfill._patch_notebook(
        _lancedb_dir(base),
        base / SLUG / DOCUMENTS_DB_FILENAME,
        parsed_root,
        slug=SLUG,
        resolve_preamble=resolve_preamble,
    )


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


# ---------------------------------------------------------------------------
# M1 — the HIT path's REAL (non-empty) preamble round-trip
# ---------------------------------------------------------------------------


class TestRealPreambleRoundTrip:
    """M1 — every other backfill test builds the table AND runs the backfill
    with ``resolve_preamble=lambda _pid: None``, so chunk_ids match by
    construction and the ``preamble_doc is not None`` branch of
    ``_rechunk_paper`` (the SOLE HIT-path dependency for source_span /
    printed_number under a real preamble) is exercised by no test. Build the
    table AND run the backfill through the SAME non-empty preamble resolver:
    the backfill must reproduce the chunk_ids (a HIT) and resolve source_span
    non-null for the theorem rows."""

    def test_hit_path_with_real_preamble_roundtrip(self, tmp_path):
        base = tmp_path / "notebooks"
        parsed = _parsed_root(tmp_path, {PAPER: HTML})
        doc = _nonempty_preamble(PAPER)
        resolver = lambda _pid: doc  # noqa: E731

        # Build the table THROUGH the non-empty preamble (NOT the None seam),
        # so the stored chunk_ids are hash(preamble_text + body_text).
        _build_table_from_html(
            tmp_path, base, parsed, PAPER, seed=21, resolve_preamble=resolver
        )
        _register(base, [_doc(PAPER)])

        # Sanity: the chunks carry the non-empty preamble_ref from the build.
        pre = _read_rows(base)
        assert pre and all(
            r["preamble_ref"] == doc.preamble_hash for r in pre.values()
        )

        # Run WITHOUT stubbing preamble to None — the SAME resolver as the build.
        assert (
            backfill.run(
                SLUG,
                base=base,
                corpus_parsed_dir=parsed,
                resolve_preamble=resolver,
            )
            == 0
        )

        rows = _read_rows(base)
        assert len(rows) == 3
        by_kind: dict[str, list] = {}
        for r in rows.values():
            by_kind.setdefault(r["kind"], []).append(r)

        # HIT: every row resolves source_span non-null (chunk_ids reproduced
        # under the non-empty preamble), carrying the authoritative txt hash.
        for r in rows.values():
            assert r["source_revision_id"] == PAPER
            assert r["source_span"] is not None, (
                f"{r['kind']} span must resolve on a real-preamble HIT"
            )
            span = json.loads(r["source_span"])
            assert span["rev"] == PARSE_SHA[:16]
            assert span["txt"] == backfill._normalized_text_hash(r["body_text"])
        # printed_number is set ONLY on a HIT — its presence proves the re-chunk
        # reproduced the ids under the preamble, not a fallback with null span.
        assert by_kind["stmt"][0]["printed_number"] == "1.1"
        assert by_kind["proof"][0]["printed_number"] == "1.1"


# ---------------------------------------------------------------------------
# M2 — the driver's own add_columns -> hydrate composition (21 -> 26 cols)
# ---------------------------------------------------------------------------


class TestMigrateThenHydrate:
    """M2 — every other backfill test builds via ``write_chunks`` (already at
    the 26-col schema), so ``_ensure_v2_columns`` returns ``[]`` and the
    migrate-then-hydrate path — add 5 columns to a genuine pre-v2 table, then
    hydrate them in the SAME run (the live go-live scenario) — is exercised by
    no test. Build a real 21-col pre-v2 table, run the backfill, and assert the
    5 columns are added AND hydrated non-null (read back from disk) with
    embeddings byte-identical."""

    def _build_pre_v2_table(
        self, tmp_path: Path, base: Path, parsed_root: Path, paper_id: str, *, seed: int
    ) -> None:
        """Materialize the notebook's chunks table at the 21-col pre-source-
        truth-m2 schema (``CHUNKS_SCHEMA_V1[:-5]``) holding real, HIT-
        reproducible rows + embeddings — the live on-disk shape BEFORE the
        backfill adds the five v2 columns.

        ``write_chunks`` always builds the full 26-col table, so harvest the
        real rows + embeddings from a throwaway build and re-materialize the
        21-col subset at the real notebook path (no ``drop_table`` needed)."""
        harvest = tmp_path / "harvest"
        _build_table_from_html(tmp_path, harvest, parsed_root, paper_id, seed=seed)
        full_rows = (
            lancedb.connect(str(_lancedb_dir(harvest)))
            .open_table("chunks")
            .to_arrow()
            .to_pylist()
        )
        pre_v2_schema = pa.schema(list(CHUNKS_SCHEMA_V1)[:-5])
        v2_cols = set(CHUNKS_SCHEMA_V1.names) - set(pre_v2_schema.names)
        assert len(pre_v2_schema.names) == 21 and len(v2_cols) == 5
        pre_rows = [
            {k: v for k, v in r.items() if k not in v2_cols} for r in full_rows
        ]
        ldir = _lancedb_dir(base)
        ldir.mkdir(parents=True, exist_ok=True)
        lancedb.connect(str(ldir)).create_table(
            "chunks", data=pa.Table.from_pylist(pre_rows, schema=pre_v2_schema)
        )

    def test_pre_v2_table_migrated_and_hydrated_in_one_run(self, tmp_path):
        base = tmp_path / "notebooks"
        parsed = _parsed_root(tmp_path, {PAPER: HTML})
        self._build_pre_v2_table(tmp_path, base, parsed, PAPER, seed=31)
        _register(base, [_doc(PAPER, license_status="eligible")])

        # The table is genuinely pre-v2: 21 columns, none of the five.
        assert len(
            lancedb.connect(str(_lancedb_dir(base)))
            .open_table("chunks")
            .schema.names
        ) == 21

        before = _read_rows(base)

        # Run via _patch_notebook so we can read report.columns_added directly.
        report = _patch(base, parsed)

        # (a) all five columns were added by the driver's own migration step.
        assert len(report.columns_added) == 5
        assert set(report.columns_added) == {
            "source_revision_id",
            "source_span",
            "truncated",
            "printed_number",
            "license_ref",
        }

        after = _read_rows(base)
        assert len(
            lancedb.connect(str(_lancedb_dir(base)))
            .open_table("chunks")
            .schema.names
        ) == 26

        # (b) the five columns are hydrated non-null on the HIT paper, read BACK
        # from the table (NOT the in-memory report). The theorem stmt row
        # carries all five; the section row's printed_number is legitimately
        # None (F1), so it is asserted separately from the always-set four.
        by_kind: dict[str, dict] = {r["kind"]: r for r in after.values()}
        stmt = by_kind["stmt"]
        for col in (
            "source_revision_id",
            "source_span",
            "truncated",
            "printed_number",
            "license_ref",
        ):
            assert stmt[col] is not None, f"{col} not hydrated on the HIT stmt row"
        assert stmt["printed_number"] == "1.1"
        assert stmt["source_revision_id"] == PAPER
        assert stmt["license_ref"] == "eligible"
        for r in after.values():
            for col in (
                "source_revision_id",
                "source_span",
                "truncated",
                "license_ref",
            ):
                assert r[col] is not None, f"{col} null on {r['kind']} row"

        # (c) embeddings byte-identical pre/post the migrate-then-hydrate path.
        assert set(before) == set(after)
        for cid, arow in after.items():
            for col in ("embedding_stmt", "embedding_proof"):
                b = before[cid][col]
                a = arow[col]
                if b is None:
                    assert a is None
                else:
                    assert np.array_equal(
                        np.asarray(b, dtype=np.float32),
                        np.asarray(a, dtype=np.float32),
                    ), f"{col} for {cid} mutated by migrate-then-hydrate"


# ---------------------------------------------------------------------------
# M3 — the chunker_rerun_failed abstention reason-code branch
# ---------------------------------------------------------------------------


class TestRerunFailedAbstention:
    """M3 — of the four source_span abstention reason codes,
    ``chunker_rerun_failed`` is the only one no test triggers. Force
    ``_rechunk_paper`` through its ``PER_PAPER_FAILURE_EXCEPTIONS`` envelope by
    making a structural-extraction pass raise, so the re-chunk returns
    ``status="rerun_failed"`` for a registered paper: source_span abstains with
    reason chunker_rerun_failed while truncated is still populated via the
    safe-direction fallback."""

    def test_rerun_failed_abstains(self, tmp_path):
        base = tmp_path / "notebooks"
        parsed = _parsed_root(tmp_path, {PAPER: HTML})
        _build_table_from_html(tmp_path, base, parsed, PAPER, seed=41)
        _register(base, [_doc(PAPER)])

        # Make the first structural pass raise a member of
        # PER_PAPER_FAILURE_EXCEPTIONS (ValueError) -> _rechunk_paper's try/except
        # converts it to a per-paper rerun_failed (not a crash), exercising the
        # real resilience envelope AND the uncovered _patch_notebook branch.
        def _boom(*_a, **_k):
            raise ValueError("synthetic malformed-HTML failure")

        with patch.object(backfill, "_extract_chunks_from_container", _boom):
            report = _patch(base, parsed)

        # The registry resolved (source_revision_id set), so the source_span
        # abstention is reason-coded chunker_rerun_failed, NOT no_source_revision.
        assert report.source_span_null_reasons["chunker_rerun_failed"] >= 1
        assert (
            report.source_span_null_reasons["chunker_rerun_failed"]
            == report.total_rows
        )
        assert report.rev_resolved == report.total_rows  # registry still joined

        rows = _read_rows(base)
        assert rows
        for r in rows.values():
            assert r["source_revision_id"] == PAPER
            assert r["source_span"] is None  # abstained
            assert r["printed_number"] is None  # not attempted on a miss
            assert r["truncated"] is not None  # fallback still populates it


# ---------------------------------------------------------------------------
# M4 — a registry-HIT + chunk-id-MISS span abstention is RE-attempted
# ---------------------------------------------------------------------------


class TestSpanReattempt:
    """M4 — the old skip-gate keyed on ``source_revision_id`` alone, so a
    registry-HIT + chunk-id-MISS paper (source_span null though the revision
    resolved) was frozen at null on every future run. The tightened gate
    RE-attempts such a paper. Run 1 re-chunks under a preamble that does NOT
    match the stored (empty-preamble) chunk_ids -> a MISS -> source_span null;
    run 2 re-chunks under the matching (empty) preamble -> a HIT -> source_span
    resolves. Embeddings stay byte-identical across both runs."""

    def test_span_null_rerun_reattempts_when_ids_reproduce(self, tmp_path):
        base = tmp_path / "notebooks"
        parsed = _parsed_root(tmp_path, {PAPER: HTML})
        # Table built with the EMPTY preamble -> stored chunk_ids = hash(body).
        _build_table_from_html(tmp_path, base, parsed, PAPER, seed=51)
        _register(base, [_doc(PAPER)])
        before = _read_rows(base)

        # Run 1: re-chunk under a NON-empty preamble -> chunk_ids differ -> MISS.
        # Registry resolves, so source_revision_id is set but source_span
        # abstains (reason chunk_id_not_reproduced).
        doc = _nonempty_preamble(PAPER)
        assert (
            backfill.run(
                SLUG,
                base=base,
                corpus_parsed_dir=parsed,
                resolve_preamble=lambda _pid: doc,
            )
            == 0
        )
        mid = _read_rows(base)
        assert all(r["source_revision_id"] == PAPER for r in mid.values())
        assert all(r["source_span"] is None for r in mid.values()), (
            "run 1 must MISS (chunk-id not reproduced under the wrong preamble)"
        )
        assert all(r["truncated"] is not None for r in mid.values())

        # Run 2: re-chunk under the MATCHING (empty) preamble -> chunk_ids
        # reproduce -> HIT. The OLD gate would SKIP (source_revision_id already
        # non-null) and freeze the null span; the tightened gate RE-attempts and
        # the span resolves.
        assert _run(base, parsed) == 0
        after = _read_rows(base)
        assert all(r["source_span"] is not None for r in after.values()), (
            "run 2 must resolve source_span (the M4 fix: span not frozen)"
        )
        for r in after.values():
            span = json.loads(r["source_span"])
            assert span["txt"] == backfill._normalized_text_hash(r["body_text"])

        # Embeddings byte-identical across both runs (0-re-embed on a reattempt).
        assert set(before) == set(after)
        for cid, arow in after.items():
            for col in ("embedding_stmt", "embedding_proof"):
                b = before[cid][col]
                a = arow[col]
                if b is None:
                    assert a is None
                else:
                    assert np.array_equal(
                        np.asarray(b, dtype=np.float32),
                        np.asarray(a, dtype=np.float32),
                    ), f"{col} for {cid} mutated across reattempt runs"


# ---------------------------------------------------------------------------
# L3 — the duplicated v2 default map must not drift from the store's
# ---------------------------------------------------------------------------


def test_v2_defaults_match_store():
    """L3 — ``backfill._V2_COLUMN_DEFAULTS`` deliberately re-mirrors the five
    source-truth-m2 entries of ``ingest.store._TEXTBOOK_MIGRATION_DEFAULTS`` (to
    keep the embedder out of the driver's import graph). Nothing else asserts
    they stay equal, so a later single-map edit could silently diverge the
    driver's self-contained migration from the store's. Importing
    ``ingest.store`` in a TEST is fine (the 0-re-embed guarantee binds the
    DRIVER's import graph, not the test's)."""
    from ingest.store import _TEXTBOOK_MIGRATION_DEFAULTS

    v2 = backfill._V2_COLUMN_DEFAULTS
    assert set(v2) == {
        "source_revision_id",
        "source_span",
        "truncated",
        "printed_number",
        "license_ref",
    }
    for key in v2:
        assert key in _TEXTBOOK_MIGRATION_DEFAULTS, f"{key} missing from store map"
        assert v2[key] == _TEXTBOOK_MIGRATION_DEFAULTS[key], (
            f"cast SQL drift for {key!r}: backfill={v2[key]!r} "
            f"store={_TEXTBOOK_MIGRATION_DEFAULTS[key]!r}"
        )
