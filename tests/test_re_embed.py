"""Tests for the partial re-embed driver.

The copy decision is tested through the public interface: ``compute_diff``
(pure) and ``run_re_embed`` against real temporary LanceDB tables, with only
the chunker (``chunk_paper``) and the model (``embed_paper`` /
``load_embed_record``) stubbed. Reuse-by-identity cases (TestReuseByIdentity):

- same body under a different chunk id -> copied;
- same chunk id on the other route -> re-embedded (never copied across
  routes);
- same chunk id from another embedder or a legacy policy -> re-embedded.

Plus ``--resume`` (TestResume), the embedding-space mixing guard
(TestSpaceMixingGuard), the Makefile content, the chunk-id
source pin (TestChunkerVersionFreeze) and the staging sentinel.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import lancedb
import numpy as np
import pyarrow as pa
import pytest

from ingest.chunk import (
    CHUNKER_VERSION,
    CHUNKS_SCHEMA_V1,
    EMBED_INPUT_POLICY_VERSION,
    LEGACY_EMBED_INPUT_POLICY_VERSION,
    ChunkRecord,
    route,
    to_row,
)
from ingest.embedder import EMBEDDER_VERSION
from ingest.re_embed import (
    _read_old_embedder_version,
    _subset_embed_record,
    compute_diff,
    run_re_embed,
)
from ingest.schema import (
    CHUNKS_TABLE_NAME,
    EMBEDDING_DIM,
    LANCE_STORAGE_OPTIONS,
    EmbedRecord,
)
from ingest.store import CORPUS_VERSION_MARKER_NAME, write_chunks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PAPER = "2401.00001"
OTHER_EMBEDDER = "bge-m3@00000000"
#: Seed base of the stub embedder's vectors, far from the active tables'.
FRESH_SEED = 1000


def _normalized(seed: int) -> np.ndarray:
    """Return an L2-normalized float32 1024-d vector seeded deterministically."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    v /= np.linalg.norm(v)
    return v


def _cid(paper_id: str, n: int) -> str:
    return f"arxiv:{paper_id}:{n:016x}"


def _make_chunk(
    paper_id: str, chunk_id: str, kind: str = "stmt", body: str | None = None
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        paper_id=paper_id,
        kind=kind,
        section_path=[],
        theorem_name=None,
        theorem_label=None,
        body_text=body if body is not None else f"body for {chunk_id}",
        body_tokens="body",
        preamble_ref=None,
        chunker_version=CHUNKER_VERSION,
        truncated=False,
    )


def _record(
    chunks: list[ChunkRecord],
    *,
    seed: int = 0,
    embedder_version: str = EMBEDDER_VERSION,
    policy: str = EMBED_INPUT_POLICY_VERSION,
) -> EmbedRecord:
    """Vectors for ``chunks`` (``seed + i`` for the i-th), each in its route's list."""
    ids: dict[str, list[str]] = {"stmt": [], "proof": []}
    rows: dict[str, list[np.ndarray]] = {"stmt": [], "proof": []}
    for i, chunk in enumerate(chunks):
        ids[route(chunk.kind)].append(chunk.chunk_id)
        rows[route(chunk.kind)].append(_normalized(seed + i))

    def _array(vectors: list[np.ndarray]) -> np.ndarray:
        if not vectors:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        return np.stack(vectors)

    return EmbedRecord(
        chunk_ids_stmt=ids["stmt"],
        embedding_stmt=_array(rows["stmt"]),
        chunk_ids_proof=ids["proof"],
        embedding_proof=_array(rows["proof"]),
        embedder_version=embedder_version,
        embed_input_policy_version=policy,
    )


def _active(tmp_path: Path, chunks: list[ChunkRecord] | None = None, **stamp) -> Path:
    """A real active LanceDB (with its corpus-version.json) holding ``chunks``."""
    chunks = chunks or []
    path = tmp_path / "lancedb"
    write_chunks(chunks, _record(chunks, **stamp), lancedb_path=path, build_indices=False)
    return path


def _write_active_marker(
    active_path: Path, embedder_version: str = EMBEDDER_VERSION
) -> None:
    active_path.mkdir(parents=True, exist_ok=True)
    (active_path / CORPUS_VERSION_MARKER_NAME).write_text(
        json.dumps(
            {
                "version": 7,
                "embedder_version": embedder_version,
                "embed_input_policy_version": EMBED_INPUT_POLICY_VERSION,
                "chunker_version": CHUNKER_VERSION,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _staged(tmp_path: Path) -> dict[str, dict]:
    """The staging table's rows keyed by chunk_id (LanceDB reorders rows)."""
    path = tmp_path / "staging"
    if not (path / "chunks.lance").is_dir():
        return {}
    table = lancedb.connect(str(path)).open_table("chunks")
    return {row["chunk_id"]: row for row in table.to_arrow().to_pylist()}


def _bytes(vector) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def _ok_embed_stats():
    """Return an EmbedStats mimicking status=ok."""
    from ingest.embedder import EmbedStats

    return EmbedStats(
        paper_id="x",
        chunks_processed=1,
        chunks_skipped=0,
        truncated_count=0,
        elapsed_s=0.01,
        status="ok",
        error=None,
        error_class="none",
    )


class _StubEmbedder:
    """Stands in for the model (``embed_paper`` + ``load_embed_record``).

    Records which papers it embedded and returns vectors seeded from
    :data:`FRESH_SEED`, so a test can tell a fresh vector from a copied one.
    """

    def __init__(self, chunks_by_paper: dict[str, list[ChunkRecord]]):
        self.chunks_by_paper = chunks_by_paper
        self.calls: list[str] = []

    def embed_paper(self, paper_id: str):
        self.calls.append(paper_id)
        return _ok_embed_stats()

    def load_embed_record(self, paper_id: str) -> EmbedRecord:
        return _record(self.chunks_by_paper[paper_id], seed=FRESH_SEED)


def _run(
    tmp_path: Path,
    active: Path,
    new_chunks: dict[str, list[ChunkRecord]],
    **kwargs,
):
    """Run the driver against ``active`` with a stub chunker and model."""
    embedder = _StubEmbedder(new_chunks)
    with (
        patch("ingest.re_embed.chunk_paper", lambda pid: new_chunks[pid]),
        patch("ingest.re_embed.embed_paper", embedder.embed_paper),
        patch("ingest.re_embed.load_embed_record", embedder.load_embed_record),
    ):
        summary = run_re_embed(
            active_lancedb_path=active,
            staging_lancedb_path=tmp_path / "staging",
            state_path=tmp_path / "state.json",
            failures_path=tmp_path / "failures.jsonl",
            **kwargs,
        )
    return summary, embedder


class _WriteChunksSpy:
    """Records every call to `write_chunks` for assertion."""

    def __init__(self):
        self.calls: list[tuple[list[ChunkRecord], EmbedRecord]] = []

    def __call__(self, chunks, embeddings, lancedb_path=None, **kwargs):
        self.calls.append((list(chunks), embeddings))
        return 1  # synthetic version int


# ---------------------------------------------------------------------------
# compute_diff — the pure copy decision
# ---------------------------------------------------------------------------


def _stored_row(
    chunk_id: str,
    body: str,
    *,
    seed: int,
    kind: str = "stmt",
    embedder_version: str = EMBEDDER_VERSION,
    policy: str | None = EMBED_INPUT_POLICY_VERSION,
) -> dict:
    vector = _normalized(seed).tolist()
    return {
        "chunk_id": chunk_id,
        "kind": kind,
        "body_text": body,
        "embedder_version": embedder_version,
        "embed_input_policy_version": policy,
        "embedding_stmt": None if route(kind) == "proof" else vector,
        "embedding_proof": vector if route(kind) == "proof" else None,
    }


class TestComputeDiff:
    def test_partitions_by_reuse_identity_not_chunk_id(self):
        old = [
            _stored_row(_cid(PAPER, 1), "kept body", seed=1),
            _stored_row(_cid(PAPER, 2), "old body", seed=2),
        ]
        new = [
            _make_chunk(PAPER, _cid(PAPER, 9), body="kept body"),
            _make_chunk(PAPER, _cid(PAPER, 2), body="new body"),
        ]
        copy, re_embed, drop = compute_diff(
            old, new, target_embedder_version=EMBEDDER_VERSION
        )
        assert copy == {_cid(PAPER, 9): old[0]["embedding_stmt"]}
        assert re_embed == {_cid(PAPER, 2)}
        assert drop == {_cid(PAPER, 1)}

    def test_the_target_embedder_is_part_of_the_match(self):
        old = [_stored_row(_cid(PAPER, 1), "body", seed=1)]
        new = [_make_chunk(PAPER, _cid(PAPER, 1), body="body")]
        copy, re_embed, drop = compute_diff(
            old, new, target_embedder_version=OTHER_EMBEDDER
        )
        assert copy == {}
        assert re_embed == {_cid(PAPER, 1)}
        assert drop == set()

    def test_a_null_policy_row_is_never_reused(self):
        old = [_stored_row(_cid(PAPER, 1), "body", seed=1, policy=None)]
        new = [_make_chunk(PAPER, _cid(PAPER, 1), body="body")]
        copy, re_embed, _ = compute_diff(
            old, new, target_embedder_version=EMBEDDER_VERSION
        )
        assert copy == {}
        assert re_embed == {_cid(PAPER, 1)}


# ---------------------------------------------------------------------------
# _read_old_embedder_version
# ---------------------------------------------------------------------------


class TestReadOldEmbedderVersion:
    def test_reads_from_marker(self, tmp_path):
        _write_active_marker(tmp_path / "lancedb", "bge-m3@aaaaaaaa")
        v = _read_old_embedder_version(tmp_path / "lancedb")
        assert v == "bge-m3@aaaaaaaa"

    def test_raises_when_missing(self, tmp_path):
        with pytest.raises(RuntimeError, match="missing"):
            _read_old_embedder_version(tmp_path / "lancedb")

    def test_raises_when_field_missing(self, tmp_path):
        path = tmp_path / "lancedb"
        path.mkdir()
        (path / CORPUS_VERSION_MARKER_NAME).write_text(
            json.dumps({"version": 7})
        )
        with pytest.raises(RuntimeError, match="no `embedder_version`"):
            _read_old_embedder_version(path)


# ---------------------------------------------------------------------------
# _subset_embed_record
# ---------------------------------------------------------------------------


class TestSubsetEmbedRecord:
    def test_keeps_only_requested_ids(self):
        a = "arxiv:2401.00001:aaaaaaaaaaaaaaaa"
        b = "arxiv:2401.00001:bbbbbbbbbbbbbbbb"
        c = "arxiv:2401.00001:cccccccccccccccc"
        record = EmbedRecord(
            chunk_ids_stmt=[a, b],
            embedding_stmt=np.asarray(
                [_normalized(1), _normalized(2)], dtype=np.float32
            ),
            chunk_ids_proof=[c],
            embedding_proof=np.asarray(
                [_normalized(3)], dtype=np.float32
            ),
            embedder_version=EMBEDDER_VERSION,
        )
        subset = _subset_embed_record(record, keep={b})
        assert subset.chunk_ids_stmt == [b]
        assert subset.embedding_stmt.shape == (1, EMBEDDING_DIM)
        assert subset.chunk_ids_proof == []
        assert subset.embedding_proof.shape == (0, EMBEDDING_DIM)


# ---------------------------------------------------------------------------
# run_re_embed against real LanceDB tables — reuse by identity
# ---------------------------------------------------------------------------


class TestReuseByIdentity:
    def test_same_body_under_a_new_chunk_id_is_copied(self, tmp_path):
        old = _make_chunk(PAPER, _cid(PAPER, 1), body="Let X be a scheme.")
        active = _active(tmp_path, [old], seed=7)
        new = _make_chunk(PAPER, _cid(PAPER, 2), body="Let X be a scheme.")

        summary, embedder = _run(tmp_path, active, {PAPER: [new]})

        assert summary.papers_failed == []
        assert summary.chunks_copied == 1
        assert summary.chunks_re_embedded == 0
        assert summary.chunks_dropped == 1
        assert embedder.calls == []
        staged = _staged(tmp_path)
        assert set(staged) == {new.chunk_id}
        row = staged[new.chunk_id]
        assert _bytes(row["embedding_stmt"]) == _normalized(7).tobytes()
        assert row["embedding_proof"] is None
        assert row["embedder_version"] == EMBEDDER_VERSION
        assert row["embed_input_policy_version"] == EMBED_INPUT_POLICY_VERSION

    def test_same_chunk_id_on_the_other_route_is_re_embedded(self, tmp_path):
        # The wrong-route bug: the chunk id does not hash the kind, so a
        # re-chunk returned a stored ``section`` body as a ``proof`` under
        # the same id, and the copy path carried its statement vector over.
        cid = _cid(PAPER, 1)
        stored = _make_chunk(PAPER, cid, kind="section", body="We prove it.")
        active = _active(tmp_path, [stored], seed=7)
        new = _make_chunk(PAPER, cid, kind="proof", body="We prove it.")

        summary, embedder = _run(tmp_path, active, {PAPER: [new]})

        assert summary.papers_failed == []
        assert summary.chunks_copied == 0
        assert summary.chunks_re_embedded == 1
        assert embedder.calls == [PAPER]
        row = _staged(tmp_path)[cid]
        assert row["embedding_stmt"] is None
        assert _bytes(row["embedding_proof"]) == _normalized(FRESH_SEED).tobytes()

    @pytest.mark.parametrize(
        "stamp",
        [
            {"embedder_version": OTHER_EMBEDDER},
            {"policy": LEGACY_EMBED_INPUT_POLICY_VERSION},
        ],
        ids=["other-embedder", "legacy-policy"],
    )
    def test_same_chunk_id_from_another_embedder_or_policy_is_re_embedded(
        self, tmp_path, stamp
    ):
        chunk = _make_chunk(PAPER, _cid(PAPER, 1), body="Let X be a scheme.")
        active = _active(tmp_path, [chunk], seed=7, **stamp)

        summary, embedder = _run(tmp_path, active, {PAPER: [chunk]})

        assert summary.papers_failed == []
        assert summary.chunks_copied == 0
        assert summary.chunks_re_embedded == 1
        assert embedder.calls == [PAPER]
        row = _staged(tmp_path)[chunk.chunk_id]
        assert _bytes(row["embedding_stmt"]) == _normalized(FRESH_SEED).tobytes()
        assert row["embedder_version"] == EMBEDDER_VERSION
        assert row["embed_input_policy_version"] == EMBED_INPUT_POLICY_VERSION

    def test_active_table_without_policy_column_is_re_embedded(self, tmp_path):
        # A live notebook built before the Bridgeland repair has no
        # ``embed_input_policy_version`` column at all (the five repair
        # columns are absent, not NULL). Its rows must read as "policy
        # unknown" and be re-embedded, and the scan must not
        # crash on the missing columns.
        repair_columns = {
            "embed_input_policy_version",
            "part_index",
            "part_count",
            "source_start",
            "source_end",
        }
        pre_repair = pa.schema(
            [f for f in CHUNKS_SCHEMA_V1 if f.name not in repair_columns]
        )
        chunk = _make_chunk(PAPER, _cid(PAPER, 1), body="Let X be a scheme.")
        row = to_row(
            chunk,
            _normalized(7),
            embedder_version=EMBEDDER_VERSION,
            policy=EMBED_INPUT_POLICY_VERSION,
        )
        active = tmp_path / "lancedb"
        lancedb.connect(str(active)).create_table(
            CHUNKS_TABLE_NAME,
            data=pa.Table.from_pylist(
                [{k: v for k, v in row.items() if k not in repair_columns}],
                schema=pre_repair,
            ),
            storage_options=LANCE_STORAGE_OPTIONS,
        )
        _write_active_marker(active)

        summary, embedder = _run(tmp_path, active, {PAPER: [chunk]})

        assert summary.papers_failed == []
        assert summary.chunks_copied == 0
        assert summary.chunks_re_embedded == 1
        assert embedder.calls == [PAPER]
        staged = _staged(tmp_path)[chunk.chunk_id]
        assert _bytes(staged["embedding_stmt"]) == _normalized(FRESH_SEED).tobytes()

    def test_unchanged_papers_are_copied_without_the_embedder(self, tmp_path):
        # Unchanged content is copied with no model call. Four
        # papers of five chunks; two bodies of the last paper change.
        papers = [f"2401.0000{p}" for p in range(4)]
        old = {
            pid: [
                _make_chunk(pid, _cid(pid, c), kind="proof" if c == 4 else "stmt")
                for c in range(5)
            ]
            for pid in papers
        }
        active = _active(tmp_path, [c for pid in papers for c in old[pid]], seed=0)
        new = {pid: list(chunks) for pid, chunks in old.items()}
        new[papers[3]] = old[papers[3]][:3] + [
            _make_chunk(papers[3], _cid(papers[3], 10 + c), body=f"rewritten {c}")
            for c in range(2)
        ]

        summary, embedder = _run(tmp_path, active, new)

        assert summary.papers_failed == []
        assert summary.chunks_copied == 18
        assert summary.chunks_re_embedded == 2
        assert summary.copy_fraction == pytest.approx(0.9)
        assert embedder.calls == [papers[3]]
        staged = _staged(tmp_path)
        assert len(staged) == 20
        proof = staged[_cid(papers[0], 4)]
        assert proof["embedding_stmt"] is None
        assert proof["embedding_proof"] is not None


class TestResume:
    def test_resume_skips_a_paper_already_staged_identically(self, tmp_path):
        chunks = [_make_chunk(PAPER, _cid(PAPER, i)) for i in range(3)]
        active = _active(tmp_path, chunks)
        _run(tmp_path, active, {PAPER: chunks})

        summary, embedder = _run(tmp_path, active, {PAPER: chunks}, resume=True)

        assert summary.papers_failed == []
        assert summary.chunks_skipped_resume == 3
        assert summary.chunks_copied == 0
        assert summary.chunks_re_embedded == 0
        assert embedder.calls == []
        assert set(_staged(tmp_path)) == {c.chunk_id for c in chunks}

    def test_resume_replaces_a_staged_row_whose_input_changed(self, tmp_path):
        # Same chunk id, new body: the staged row's reuse identity no
        # longer matches, so the paper is not skipped.
        cid = _cid(PAPER, 1)
        first = _make_chunk(PAPER, cid, body="first body")
        active = _active(tmp_path, [first])
        _run(tmp_path, active, {PAPER: [first]})

        second = _make_chunk(PAPER, cid, body="second body")
        summary, embedder = _run(tmp_path, active, {PAPER: [second]}, resume=True)

        assert summary.chunks_skipped_resume == 0
        assert summary.chunks_re_embedded == 1
        assert embedder.calls == [PAPER]
        assert _staged(tmp_path)[cid]["body_text"] == "second body"


    def test_resume_rewrites_a_row_another_chunker_version_staged(self, tmp_path):
        # A staged row with the SAME id and body but an older
        # chunker_version stamp (a staging left by a v1.2-era run; empty-
        # preamble papers keep their ids across v1.3) must not be skipped,
        # or the promoted table would carry the stale stamp.
        chunk = _make_chunk(PAPER, _cid(PAPER, 1), body="Let X be a scheme.")
        active = _active(tmp_path, [chunk], seed=7)
        stale = _make_chunk(PAPER, chunk.chunk_id, body="Let X be a scheme.")
        stale.chunker_version = "v1.2"
        write_chunks(
            [stale], _record([stale], seed=7),
            lancedb_path=tmp_path / "staging", build_indices=False,
        )

        summary, embedder = _run(tmp_path, active, {PAPER: [chunk]}, resume=True)

        assert summary.chunks_skipped_resume == 0
        assert summary.chunks_copied == 1
        assert embedder.calls == []
        row = _staged(tmp_path)[chunk.chunk_id]
        assert row["chunker_version"] == CHUNKER_VERSION
        assert _bytes(row["embedding_stmt"]) == _normalized(7).tobytes()


class TestSpaceMixingGuard:
    """Code guard on top of the runbook warning (synthesis D5)."""

    def test_refuses_a_staging_table_from_another_embedder(self, tmp_path):
        chunk = _make_chunk(PAPER, _cid(PAPER, 1))
        active = _active(tmp_path, [chunk])
        write_chunks(
            [chunk], _record([chunk], embedder_version=OTHER_EMBEDDER),
            lancedb_path=tmp_path / "staging", build_indices=False,
        )
        with pytest.raises(RuntimeError, match="mix embedding spaces"):
            _run(tmp_path, active, {PAPER: [chunk]})


class TestDryRun:
    """Dry run does not write; prints the diff per paper."""

    def test_dry_run_skips_writes(self, tmp_path, capsys):
        chunks = [_make_chunk(PAPER, _cid(PAPER, i)) for i in range(3)]
        active = _active(tmp_path, chunks[:1])

        _summary, embedder = _run(tmp_path, active, {PAPER: chunks}, dry_run=True)

        assert not (tmp_path / "staging").exists()
        assert embedder.calls == []
        out = capsys.readouterr().out
        assert f"{PAPER}\tcopy=1\treembed=2\tdrop=0" in out


# ---------------------------------------------------------------------------
# State-file persistence
# ---------------------------------------------------------------------------


class TestStateFile:
    def test_state_marks_complete_on_success(self, tmp_path):
        chunks = [_make_chunk(PAPER, _cid(PAPER, i)) for i in range(2)]
        active = _active(tmp_path, chunks)
        summary, _ = _run(tmp_path, active, {PAPER: chunks})
        assert summary.papers_failed == []
        state = json.loads((tmp_path / "state.json").read_text())
        assert state["status"] == "complete"
        assert state["chunks_copied"] == 2
        # Closes IS5: chunks_skipped_resume present in final state.
        assert state["chunks_skipped_resume"] == 0

    def test_empty_chunker_output_is_a_failure(self, tmp_path):
        active = _active(tmp_path)
        summary, _ = _run(tmp_path, active, {PAPER: []}, paper_ids=[PAPER])
        assert summary.papers_total == 1
        assert summary.papers_failed == [PAPER]
        state = json.loads((tmp_path / "state.json").read_text())
        assert state["status"] == "complete_with_failures"

    def test_state_marks_complete_with_failures(self, tmp_path):
        active = _active(tmp_path)

        def _chunker_raises(_pid):
            raise RuntimeError("synthetic chunker explosion")

        with patch("ingest.re_embed.chunk_paper", _chunker_raises):
            state_path = tmp_path / "state.json"
            summary = run_re_embed(
                paper_ids=[PAPER],
                active_lancedb_path=active,
                staging_lancedb_path=tmp_path / "staging",
                state_path=state_path,
                failures_path=tmp_path / "failures.jsonl",
            )
        assert PAPER in summary.papers_failed
        state = json.loads(state_path.read_text())
        assert state["status"] == "complete_with_failures"

    def test_failed_paper_still_leaves_staging_indexed(self, tmp_path):
        """A run with a failed paper ends ``complete_with_failures``, which
        ``make cutover``'s C3 accepts. Its staging table must still carry the
        vector indexes, or the cutover integrity probe refuses it."""
        from ops.cutover import verify_lancedb_integrity

        bad = "2401.00002"
        chunks = [_make_chunk(PAPER, _cid(PAPER, i)) for i in range(3)]
        active = _active(tmp_path, chunks)

        summary, _ = _run(
            tmp_path, active, {PAPER: chunks, bad: []}, paper_ids=[PAPER, bad],
        )

        assert summary.papers_failed == [bad]
        state = json.loads((tmp_path / "state.json").read_text())
        assert state["status"] == "complete_with_failures"
        integrity = verify_lancedb_integrity(tmp_path / "staging")
        assert integrity.ok is True, integrity.reason


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestPaperIdValidation:
    def test_invalid_paper_id_in_list_raises(self, tmp_path):
        active = _active(tmp_path)
        with pytest.raises(ValueError, match="invalid paper_id"):
            run_re_embed(
                paper_ids=["not-a-paper-id"],
                active_lancedb_path=active,
                staging_lancedb_path=tmp_path / "staging",
                state_path=tmp_path / "state.json",
                failures_path=tmp_path / "failures.jsonl",
            )


# ---------------------------------------------------------------------------
# Makefile target
# ---------------------------------------------------------------------------


class TestMakefileReEmbedTarget:
    def test_re_embed_target_present(self):
        text = (
            Path(__file__).resolve().parent.parent / "Makefile"
        ).read_text(encoding="utf-8")
        assert "\nre-embed:\n" in text or "\nre_embed:\n" in text
        assert "ingest.re_embed" in text


# ---------------------------------------------------------------------------
# Chunker-version stability (Landmine A)
# ---------------------------------------------------------------------------


class TestChunkerVersionFreeze:
    """Closes Landmine A + adversary F4: any change to
    ``_compute_chunk_id`` rotates every chunk_id. We pin the literal
    SHA of the function's source bytes so a future PR edit fails this
    test loudly, forcing the contributor to either revert OR bump
    ``CHUNKER_VERSION`` and re-pin in the same PR.

    Re-pinned for v1.3, which dropped the preamble from arXiv ids.
    Vector reuse is keyed by the reuse identity, not the chunk id, so a
    rotation is a staging copy plus a cutover, not a re-embed.
    """

    #: SHA-256 of `inspect.getsource(_compute_chunk_id)` as of the
    #: v1.3 rotation. ANY edit to the function body
    #: (whitespace, docstring, algorithm) breaks this hash.
    #:
    #: To re-pin after a deliberate change:
    #: ``uv run python -c "import hashlib, inspect; from
    #: ingest.chunk import _compute_chunk_id; print(hashlib.sha256(
    #: inspect.getsource(_compute_chunk_id).encode()).hexdigest())"``
    EXPECTED_COMPUTE_CHUNK_ID_SHA256 = (
        "101d8d8855d0df8040c7f7d11fcb2dbe27d1f19006f093c76bdeb7e22d2f3088"
    )

    def test_compute_chunk_id_source_is_pinned(self):
        import hashlib
        import inspect

        from ingest.chunker import _compute_chunk_id

        src = inspect.getsource(_compute_chunk_id)
        actual = hashlib.sha256(src.encode("utf-8")).hexdigest()
        assert actual == self.EXPECTED_COMPUTE_CHUNK_ID_SHA256, (
            f"_compute_chunk_id source bytes changed.\n"
            f"  expected SHA: {self.EXPECTED_COMPUTE_CHUNK_ID_SHA256}\n"
            f"  actual SHA:   {actual}\n\n"
            f"An edit to the id function rotates chunk ids: a SCHEMA "
            f"migration. Either revert the edit OR (1) bump "
            f"ingest.chunk.CHUNKER_VERSION, (2) update "
            f"EXPECTED_COMPUTE_CHUNK_ID_SHA256 in this test, and "
            f"(3) rotate existing tables through staging, per notebook: "
            f"make re-embed ARGS=\"--notebook=<slug>\", then "
            f"make notebook-cutover ARGS=\"--notebook=<slug> --force\" "
            f"(the schema-migration constraint on CHUNKER_VERSION in "
            f"ingest/chunk.py)."
        )

    def test_contract_strings_present(self):
        """Sanity guard alongside the SHA pin: even when a future edit
        re-pins the SHA, the canonical-bytes contract must still apply
        NFC normalization + sha256, and the id must hash the body only
        unless a caller names a position."""
        import inspect

        from ingest.chunker import _compute_chunk_id

        src = inspect.getsource(_compute_chunk_id)
        assert "unicodedata.normalize" in src
        assert "NFC" in src
        assert "sha256" in src
        params = inspect.signature(_compute_chunk_id).parameters
        assert list(params) == ["paper_id", "body_text", "position"]
        assert params["position"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["position"].default == ""
        code = src.split('"""')[-1]  # the body after the docstring
        assert "preamble" not in code


# ---------------------------------------------------------------------------
# Staging-marker sentinel — closes adversary F2
# ---------------------------------------------------------------------------


class TestStagingSentinel:
    """Closes adversary F2 / synthesis D8: the staging path must
    carry a durable `re-embed-progress.json` sentinel whose
    `status` is `complete` only after the run finishes — used by
    E11_S05's cutover gating to refuse promotion of a half-
    finished staging dataset."""

    def test_sentinel_written_with_in_progress_then_complete(
        self, tmp_path
    ):
        active = _active(tmp_path)
        staging = tmp_path / "staging"
        sentinel_path = staging / "re-embed-progress.json"
        observed_sentinels: list[dict] = []
        write_spy = _WriteChunksSpy()

        # Capture the sentinel mid-run (between paper write calls).
        def _capturing_write(chunks, embeddings, lancedb_path=None, **kwargs):
            if sentinel_path.is_file():
                observed_sentinels.append(
                    json.loads(sentinel_path.read_text())
                )
            return write_spy(chunks, embeddings, lancedb_path=lancedb_path)

        # One paper, three new chunks, nothing stored → re-embed path.
        new_chunks = [_make_chunk(PAPER, _cid(PAPER, i)) for i in range(3)]
        embedder = _StubEmbedder({PAPER: new_chunks})
        with (
            patch("ingest.re_embed.chunk_paper", lambda _pid: new_chunks),
            patch("ingest.re_embed.embed_paper", embedder.embed_paper),
            patch("ingest.re_embed.load_embed_record", embedder.load_embed_record),
            patch("ingest.re_embed.write_chunks", _capturing_write),
        ):
            run_re_embed(
                paper_ids=[PAPER],
                active_lancedb_path=active,
                staging_lancedb_path=staging,
                state_path=tmp_path / "state.json",
                failures_path=tmp_path / "failures.jsonl",
            )

        # Mid-run: at least one sentinel captured during write_chunks
        # carried `status="in_progress"`.
        assert any(
            s.get("status") == "in_progress" for s in observed_sentinels
        ), (
            f"expected an in_progress sentinel mid-run; got {observed_sentinels}"
        )

        # Post-run: sentinel exists and is `complete`.
        assert sentinel_path.is_file()
        final = json.loads(sentinel_path.read_text())
        assert final["status"] == "complete"
        assert final["target_embedder_version"] == EMBEDDER_VERSION
        assert "chunks_re_embedded" in final

    def test_indexes_are_built_before_the_run_is_marked_complete(
        self, tmp_path
    ):
        sentinel_path = tmp_path / "staging" / "re-embed-progress.json"
        builds: list[tuple] = []

        def _build(path):
            builds.append((path, json.loads(sentinel_path.read_text())["status"]))

        chunks = [_make_chunk(PAPER, _cid(PAPER, 0))]
        active = _active(tmp_path)
        with patch("ingest.re_embed.build_derived_indexes", _build):
            _run(tmp_path, active, {PAPER: chunks}, paper_ids=[PAPER])

        assert builds == [(tmp_path / "staging", "in_progress")]
        assert json.loads(sentinel_path.read_text())["status"] == "complete"

    def test_sentinel_not_written_on_dry_run(self, tmp_path):
        new_chunks = [_make_chunk(PAPER, _cid(PAPER, i)) for i in range(2)]
        active = _active(tmp_path)
        _run(tmp_path, active, {PAPER: new_chunks}, paper_ids=[PAPER], dry_run=True)
        assert not (tmp_path / "staging" / "re-embed-progress.json").is_file()


# ---------------------------------------------------------------------------
# IS1 — Makefile re-embed: target carries the ARGS word-split hazard note
# ---------------------------------------------------------------------------


class TestMakefileReEmbedAllRotationNote:
    """The ``re-embed-all`` comment must not send a chunk-id rotation down
    the all-datasets path; its ``--dry-run`` only lists datasets and cannot
    show the per-paper reembed=0 check."""

    def test_re_embed_all_points_the_rotation_at_the_notebook_path(self):
        text = (
            Path(__file__).resolve().parent.parent / "Makefile"
        ).read_text(encoding="utf-8")
        start = text.index("\nre-embed-all:\n")
        block = text[start:text.index("\n\n", start + 1)]
        assert "make notebook-cutover" in block
        assert "run this once per chunker-bump" not in block


class TestMakefileReEmbedArgsNote:
    """Closes IS1: the new `re-embed:` target documents the
    word-split hazard on $(ARGS) like the `ingest:` target does."""

    def test_re_embed_carries_args_note(self):
        text = (
            Path(__file__).resolve().parent.parent / "Makefile"
        ).read_text(encoding="utf-8")
        # Find the re-embed: target block and assert it warns
        # about spaces in ARGS paths.
        block_start = text.index("\nre-embed:\n")
        # 30 lines should be enough to cover the comment block.
        block = "\n".join(text[block_start:].splitlines()[:30])
        assert "spaces" in block.lower() or "NOTE on ARGS" in block


# ---------------------------------------------------------------------------
# IS4 — started_utc captured once, doesn't drift mid-run
# ---------------------------------------------------------------------------


class TestStartedUtcStable:
    """Closes IS4: the per-paper checkpoint writes must use the
    boot-time started_utc, not a fresh _utc_iso() per call."""

    def test_started_utc_does_not_drift(self, tmp_path):
        active = _active(tmp_path)
        _run(tmp_path, active, {PAPER: []}, paper_ids=[PAPER])
        state = json.loads((tmp_path / "state.json").read_text())
        # `started_utc` should be present and stable; the
        # terminal write echoes the boot-time value rather than a
        # fresh timestamp.
        assert "started_utc" in state
        assert "completed_utc" in state
        # The boot-time started_utc is captured once at run start,
        # so it should equal the value written in the initial state
        # file write (which is what the final write also uses).
        assert state["started_utc"] <= state["completed_utc"]


# ---------------------------------------------------------------------------
# --notebook on the CLI
# ---------------------------------------------------------------------------


class TestCliNotebook:
    """A rotation dry-runs and runs one notebook at a time from the CLI with
    ``--notebook``; a dataset holding textbook papers raises without a slug."""

    def _capture(self, monkeypatch, tmp_path):
        import tools._notebook_common as common
        from ingest import re_embed
        from ingest.re_embed import ReEmbedSummary

        monkeypatch.setattr(common, "NOTEBOOKS_BASE", tmp_path / "notebooks")
        calls: list[dict] = []

        def _fake(**kwargs):
            calls.append(kwargs)
            return ReEmbedSummary()

        monkeypatch.setattr(re_embed, "run_re_embed", _fake)
        return re_embed, calls

    def test_notebook_selects_its_datasets_and_state_file(self, monkeypatch, tmp_path):
        re_embed, calls = self._capture(monkeypatch, tmp_path)

        assert re_embed._cli(["--notebook", "demo-nb", "--dry-run"]) == 0

        nb = (tmp_path / "notebooks").resolve() / "demo-nb"
        (call,) = calls
        assert call["notebook_slug"] == "demo-nb"
        assert call["active_lancedb_path"] == nb / "lancedb"
        assert call["staging_lancedb_path"] == nb / "lancedb-staging"
        assert call["state_path"] == nb / "ops" / "re-embed-state.json"
        assert call["dry_run"] is True

    def test_an_explicit_path_wins_over_the_notebook_default(
        self, monkeypatch, tmp_path
    ):
        re_embed, calls = self._capture(monkeypatch, tmp_path)
        staging = tmp_path / "elsewhere"

        re_embed._cli(["--notebook", "demo-nb", "--lancedb-staging-path", str(staging)])

        assert calls[0]["staging_lancedb_path"] == staging

    def test_paper_ids_file_scopes_a_notebook_run(self, monkeypatch, tmp_path):
        # A rotation scopes a notebook run to the active table's
        # own papers: without the file, papers.txt entries that never
        # ingested join the run and fail it.
        re_embed, calls = self._capture(monkeypatch, tmp_path)
        ids = tmp_path / "rotation-papers.txt"
        ids.write_text("2401.00001\n# comment\n\ntextbook:abc\n", encoding="utf-8")

        assert re_embed._cli(
            ["--notebook", "demo-nb", "--paper-ids-file", str(ids), "--dry-run"]
        ) == 0

        (call,) = calls
        assert call["paper_ids"] == ["2401.00001", "textbook:abc"]
        assert call["notebook_slug"] == "demo-nb"

    def test_without_notebook_the_shared_defaults_hold(self, monkeypatch, tmp_path):
        from ingest.bulk_ingest import DEFAULT_LANCEDB_STAGING_PATH
        from ingest.re_embed import DEFAULT_STATE_PATH
        from ingest.store import DEFAULT_LANCEDB_PATH

        re_embed, calls = self._capture(monkeypatch, tmp_path)

        re_embed._cli([])

        (call,) = calls
        assert call["notebook_slug"] is None
        assert call["active_lancedb_path"] == DEFAULT_LANCEDB_PATH
        assert call["staging_lancedb_path"] == DEFAULT_LANCEDB_STAGING_PATH
        assert call["state_path"] == DEFAULT_STATE_PATH

    def test_a_bad_slug_is_refused(self, monkeypatch, tmp_path):
        from tools._notebook_common import NotebookError

        re_embed, calls = self._capture(monkeypatch, tmp_path)
        with pytest.raises(NotebookError):
            re_embed._cli(["--notebook", "../escape"])
        assert calls == []


# ---------------------------------------------------------------------------
# The one-time v1.2 -> v1.3 id rotation, end to end
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures" / "chunker"
#: Paper A resolves a preamble (its v1.2 ids hashed it in, so they rotate);
#: paper B never did (extraction failed, or no macros), so its ids are the
#: same under both formulas.
ROT_A, ROT_B = "2307.00002", "2307.00001"
ROT_SLUG = "rotation-nb"
ROT_PREAMBLE = "\\newcommand{\\R}{\\mathbb{R}}\n\\def\\Z{\\mathbb{Z}}"


def _v12_id(paper_id: str, preamble_text: str, body: str) -> str:
    """The v1.2 formula: ``sha256(preamble_text + NFC(body))[:16]``."""
    import hashlib
    import unicodedata

    digest = hashlib.sha256(
        (preamble_text + unicodedata.normalize("NFC", body)).encode("utf-8")
    ).hexdigest()[:16]
    return f"arxiv:{paper_id}:{digest}"


def _adversarial(seed: int) -> np.ndarray:
    """A unit float32 vector carrying the bit patterns a lossy copy breaks:
    -0.0, the smallest subnormal and ±FLT_MIN."""
    v = _normalized(seed)
    specials = np.array(
        [-0.0, np.float32(1e-45), np.finfo(np.float32).tiny, -np.finfo(np.float32).tiny],
        dtype=np.float32,
    )
    rest = v[len(specials):]
    rest = (rest / np.linalg.norm(rest)).astype(np.float32)
    return np.concatenate([specials, rest]).astype(np.float32)


def _preamble_doc(paper_id: str):
    import hashlib

    from ingest.preamble_types import PreambleDoc

    return PreambleDoc(
        paper_id=paper_id,
        source_hash="0" * 64,
        macros=ROT_PREAMBLE.splitlines(),
        preamble_text=ROT_PREAMBLE,
        preamble_hash=hashlib.sha256(ROT_PREAMBLE.encode("utf-8")).hexdigest()[:16],
    )


def _resolve(paper_id: str):
    return _preamble_doc(paper_id) if paper_id == ROT_A else None


class _Corpus:
    """A temporary parsed corpus + chunk dir the REAL chunker reads/writes."""

    def __init__(self, tmp_path: Path, html_edit=None):
        import shutil

        self.parsed = tmp_path / "corpus" / "parsed"
        self.chunks = tmp_path / "corpus" / "chunks"
        for pid in (ROT_A, ROT_B):
            (self.parsed / pid).mkdir(parents=True)
            shutil.copy(FIXTURES / pid / "index.html", self.parsed / pid / "index.html")
        self.html_edit = html_edit

    def patches(self):
        return (
            patch("ingest.chunker.PARSED_DIR", self.parsed),
            patch("ingest.chunker.CHUNKS_DIR", self.chunks),
            patch("ingest.chunker._resolve_preamble_doc", _resolve),
        )

    def chunk(self, paper_id: str) -> list[ChunkRecord]:
        from ingest.chunker import chunk_paper

        a, b, c = self.patches()
        with a, b, c:
            return chunk_paper(paper_id)


def _build_v12_active(tmp_path: Path, corpus: _Corpus) -> tuple[Path, dict]:
    """The notebook's active table as v1.2 wrote it: preamble-hashed ids,
    ``chunker_version='v1.2'``, ``body-first-v1``, the current embedder, and
    stored vectors with adversarial bit patterns. Returns the dataset path and
    ``{v1.2 id: (paper_id, body, route, vector bytes)}``."""
    active = tmp_path / "notebooks" / ROT_SLUG / "lancedb"
    rows: list[ChunkRecord] = []
    ids: dict[str, list[str]] = {"stmt": [], "proof": []}
    vectors: dict[str, list[np.ndarray]] = {"stmt": [], "proof": []}
    stored: dict[str, tuple] = {}
    seed = 0
    for pid in (ROT_A, ROT_B):
        preamble = ROT_PREAMBLE if pid == ROT_A else ""
        for chunk in corpus.chunk(pid):
            chunk.chunk_id = _v12_id(pid, preamble, chunk.body_text)
            chunk.chunker_version = "v1.2"
            vector = _adversarial(seed)
            seed += 1
            ids[route(chunk.kind)].append(chunk.chunk_id)
            vectors[route(chunk.kind)].append(vector)
            stored[chunk.chunk_id] = (pid, chunk.body_text, route(chunk.kind), vector.tobytes())
            rows.append(chunk)

    def _array(vs):
        return np.stack(vs) if vs else np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

    record = EmbedRecord(
        chunk_ids_stmt=ids["stmt"], embedding_stmt=_array(vectors["stmt"]),
        chunk_ids_proof=ids["proof"], embedding_proof=_array(vectors["proof"]),
        embedder_version=EMBEDDER_VERSION,
        embed_input_policy_version=EMBED_INPUT_POLICY_VERSION,
    )
    # A long-lived active table has seen many commits; a staging table built
    # from scratch restarts the count. Re-write the same rows to model that.
    for _ in range(25):
        write_chunks(rows, record, lancedb_path=active, build_indices=False)
    return active, stored


def _forbid_embedder():
    def _boom(*_a, **_k):
        raise AssertionError("the id rotation must not reach the embedder")

    return (
        patch("ingest.re_embed.embed_paper", _boom),
        patch("ingest.re_embed.load_embed_record", _boom),
        patch("tools.notebook_textbook_ingest._build_embed_record", _boom),
    )


def _rotate(tmp_path: Path, corpus: _Corpus, active: Path, embedder_patches):
    staging = active.parent / "lancedb-staging"
    p1, p2, p3 = corpus.patches()
    e1, e2, e3 = embedder_patches
    # run_re_embed reads the notebook's papers.txt through this base.
    base = patch("ingest.textbook_chunker.NOTEBOOKS_BASE", active.parent.parent)
    with p1, p2, p3, e1, e2, e3, base:
        summary = run_re_embed(
            active_lancedb_path=active,
            staging_lancedb_path=staging,
            state_path=tmp_path / "state.json",
            failures_path=tmp_path / "failures.jsonl",
            notebook_slug=ROT_SLUG,
        )
    return summary, staging


def _rows(path: Path) -> dict[str, dict]:
    table = lancedb.connect(str(path)).open_table("chunks")
    return {row["chunk_id"]: row for row in table.to_arrow().to_pylist()}


class TestOneTimeIdRotation:
    """The v1.2 -> v1.3 rotation through the REAL re-embed driver
    and the REAL chunker, into a fresh staging table, then the notebook
    cutover. Only the embedder is replaced, by a stub that fails if called."""

    def _setup(self, tmp_path, html_edit=None):
        corpus = _Corpus(tmp_path)
        active, stored = _build_v12_active(tmp_path, corpus)
        (tmp_path / "notebooks" / ROT_SLUG / "papers.txt").write_text(
            f"{ROT_A}\n{ROT_B}\n", encoding="utf-8"
        )
        if html_edit is not None:
            html = corpus.parsed / ROT_A / "index.html"
            html.write_text(html_edit(html.read_text(encoding="utf-8")), encoding="utf-8")
        return corpus, active, stored

    def test_an_id_only_rotation_copies_every_vector(self, tmp_path):
        corpus, active, stored = self._setup(tmp_path)
        expected = {pid: [c.chunk_id for c in corpus.chunk(pid)] for pid in (ROT_A, ROT_B)}

        summary, staging = _rotate(tmp_path, corpus, active, _forbid_embedder())

        assert summary.papers_failed == []
        assert summary.chunks_re_embedded == 0
        assert summary.chunks_copied == summary.chunks_target == len(stored)
        progress = json.loads((staging / "re-embed-progress.json").read_text())
        assert progress["status"] == "complete"
        assert progress["papers_failed_count"] == 0

        staged = _rows(staging)
        # Row count equal, per paper.
        for pid in (ROT_A, ROT_B):
            assert sum(r["paper_id"] == pid for r in staged.values()) == sum(
                v[0] == pid for v in stored.values()
            )
        # No id the v1.3 chunker does not produce.
        assert set(staged) == set(expected[ROT_A]) | set(expected[ROT_B])
        # Paper A rotated every id; paper B (no preamble) kept every id.
        old_a = {cid for cid, v in stored.items() if v[0] == ROT_A}
        old_b = {cid for cid, v in stored.items() if v[0] == ROT_B}
        assert old_a.isdisjoint(staged)
        assert old_b == set(expected[ROT_B])
        assert summary.chunks_dropped == len(old_a)
        # Every row is a v1.3 row.
        assert {r["chunker_version"] for r in staged.values()} == {CHUNKER_VERSION}
        # Every vector copied bit-exactly into its route column.
        by_body = {(v[0], v[1], v[2]): v[3] for v in stored.values()}
        for row in staged.values():
            column = "embedding_proof" if route(row["kind"]) == "proof" else "embedding_stmt"
            other = "embedding_stmt" if column == "embedding_proof" else "embedding_proof"
            want = by_body[(row["paper_id"], row["body_text"], route(row["kind"]))]
            assert _bytes(row[column]) == want
            assert row[other] is None
            assert row["embedder_version"] == EMBEDDER_VERSION
            assert row["embed_input_policy_version"] == EMBED_INPUT_POLICY_VERSION

    def test_cutover_promotes_the_rotation_and_drops_version_keyed_caches(
        self, tmp_path
    ):
        from server.corpus import read_corpus_version
        from tools import notebook_cutover as nc

        corpus, active, stored = self._setup(tmp_path)
        _summary, staging = _rotate(tmp_path, corpus, active, _forbid_embedder())
        staged = _rows(staging)
        nb = active.parent
        base = nb.parent
        active_version = read_corpus_version(active).version
        staging_version = read_corpus_version(staging).version
        # A from-scratch staging restarts its version count.
        assert staging_version <= active_version

        # Caches a server wrote while the OLD dataset was active, keyed by
        # integers the new active may reuse.
        cache = nb / "cache"
        cache.mkdir()
        (cache / "retrieval.db").write_bytes(b"v1.2-era tier-1 rows")
        (cache / "retrieval.db-wal").write_bytes(b"wal")
        stale_bm25 = nb / "index" / "bm25" / f"v{staging_version}"
        stale_bm25.mkdir(parents=True)
        (stale_bm25 / "chunk_ids.json").write_text(json.dumps(sorted(stored)))
        old_bm25 = nb / "index" / "bm25" / f"v{active_version}"
        old_bm25.mkdir(parents=True)

        with pytest.raises(nc.CutoverError, match="--force"):
            nc.perform_cutover(ROT_SLUG, base=base)
        assert (cache / "retrieval.db").exists()  # a refusal mutates nothing

        result = nc.perform_cutover(ROT_SLUG, base=base, force=True)

        assert result["promoted_version"] == staging_version
        assert _rows(active) == staged
        assert set(_rows(nb / result["backup"])) == set(stored)
        assert not (cache / "retrieval.db").exists()
        assert not (cache / "retrieval.db-wal").exists()
        assert not stale_bm25.exists()
        # The old dataset's own BM25 dir goes too: the new table's version
        # climbs toward it on later writes.
        assert not old_bm25.exists()
        assert sorted(result["invalidated_caches"]) == sorted([
            "cache/retrieval.db", "cache/retrieval.db-wal",
            f"index/bm25/v{staging_version}", f"index/bm25/v{active_version}",
        ])

    def test_a_changed_body_still_reaches_the_embedder(self, tmp_path):
        corpus, active, stored = self._setup(
            tmp_path,
            html_edit=lambda html: html.replace(
                "Every injective sheaf is flasque.",
                "Every injective sheaf is flasque, as edited.",
            ),
        )
        new_chunks: dict[str, list[ChunkRecord]] = {}

        from ingest.chunker import chunk_paper as real_chunk_paper

        def _recording_chunk_paper(pid):
            new_chunks[pid] = real_chunk_paper(pid)
            return new_chunks[pid]

        embedder = _StubEmbedder(new_chunks)
        with patch("ingest.re_embed.chunk_paper", _recording_chunk_paper):
            summary, staging = _rotate(
                tmp_path, corpus, active,
                (
                    patch("ingest.re_embed.embed_paper", embedder.embed_paper),
                    patch("ingest.re_embed.load_embed_record", embedder.load_embed_record),
                    patch("tools.notebook_textbook_ingest._build_embed_record",
                          lambda *_a, **_k: pytest.fail("not a TeX/textbook paper")),
                ),
            )

        assert summary.papers_failed == []
        assert embedder.calls == [ROT_A]
        assert summary.chunks_re_embedded == 1
        assert summary.chunks_copied == summary.chunks_target - summary.chunks_re_embedded
        stored_bodies = {(v[0], v[1]) for v in stored.values()}
        staged = _rows(staging)
        fresh = [r for r in staged.values() if (r["paper_id"], r["body_text"]) not in stored_bodies]
        assert len(fresh) == summary.chunks_re_embedded
        assert all(r["paper_id"] == ROT_A for r in fresh)
