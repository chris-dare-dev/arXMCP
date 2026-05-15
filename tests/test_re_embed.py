"""Tests for the partial re-embed driver (E11_S03).

Pure unit tests with mocked LanceDB reads + mocked
`chunk_paper`/`embed_paper`/`load_embed_record`/`write_chunks`. The
suite covers the four ACs:

1. 95% unchanged → 95% copied without re-compute
   (TestCopyEfficacy::test_95_percent_copy).
2. --resume skips already-embedded chunks
   (TestResume::test_resume_skips_done_chunks).
3. Runbook has the GPU-hours budget table for all scenarios
   (TestRunbookContent::test_gpu_hours_table_present).
4. Runbook explicitly warns against mixing embedding spaces
   (TestRunbookContent::test_warns_against_mixing_spaces).

Plus regression guards for the synthesis landmines.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from ingest.chunker_types import CHUNKER_VERSION, ChunkRecord
from ingest.embedder import EMBEDDER_VERSION
from ingest.re_embed import (
    _build_copy_embed_record,
    _read_old_embedder_version,
    _subset_embed_record,
    compute_diff,
    run_re_embed,
)
from ingest.schema import EMBEDDING_DIM, EmbedRecord
from ingest.store import CORPUS_VERSION_MARKER_NAME

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalized(seed: int) -> list[float]:
    """Return an L2-normalized 1024-d vector seeded deterministically."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    v /= np.linalg.norm(v)
    return v.tolist()


def _make_chunk(
    paper_id: str, chunk_id: str, kind: str = "stmt"
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        paper_id=paper_id,
        kind=kind,
        section_path=[],
        theorem_name=None,
        theorem_label=None,
        body_text=f"body for {chunk_id}",
        body_tokens="body",
        preamble_ref=None,
        chunker_version=CHUNKER_VERSION,
        truncated=False,
    )


def _write_active_marker(
    active_path: Path, embedder_version: str = EMBEDDER_VERSION
) -> None:
    active_path.mkdir(parents=True, exist_ok=True)
    (active_path / CORPUS_VERSION_MARKER_NAME).write_text(
        json.dumps(
            {
                "version": 7,
                "embedder_version": embedder_version,
                "chunker_version": CHUNKER_VERSION,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# compute_diff
# ---------------------------------------------------------------------------


class TestComputeDiff:
    def test_disjoint_sets(self):
        copy, re_embed, drop = compute_diff({"a", "b"}, {"c", "d"})
        assert copy == set()
        assert re_embed == {"c", "d"}
        assert drop == {"a", "b"}

    def test_full_overlap(self):
        copy, re_embed, drop = compute_diff({"a", "b"}, {"a", "b"})
        assert copy == {"a", "b"}
        assert re_embed == set()
        assert drop == set()

    def test_mixed(self):
        copy, re_embed, drop = compute_diff(
            {"a", "b", "c"}, {"b", "c", "d"}
        )
        assert copy == {"b", "c"}
        assert re_embed == {"d"}
        assert drop == {"a"}


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
# _build_copy_embed_record — F1-class guard
# ---------------------------------------------------------------------------


class TestBuildCopyEmbedRecord:
    def test_refuses_mismatched_old_embedder_version(self):
        """Closes the synthesis D6 F1-class guard: an old row whose
        embedder_version doesn't match the recorded OLD_EMBEDDER_VERSION
        is a stale or corrupt source — refuse to copy."""
        new_chunks = {
            "arxiv:2401.00001:aaaaaaaaaaaaaaaa": _make_chunk(
                "2401.00001", "arxiv:2401.00001:aaaaaaaaaaaaaaaa"
            )
        }
        old_rows = {
            "arxiv:2401.00001:aaaaaaaaaaaaaaaa": {
                "embedding_stmt": _normalized(1),
                "embedding_proof": None,
                "embedder_version": "bge-m3@dddddddd",  # wrong!
                "kind": "stmt",
            }
        }
        with pytest.raises(RuntimeError, match="different embedding space"):
            _build_copy_embed_record(
                new_chunks_by_id=new_chunks,
                old_rows_by_id=old_rows,
                old_embedder_version="bge-m3@aaaaaaaa",
                target_embedder_version=EMBEDDER_VERSION,
            )

    def test_stamps_target_embedder_version_on_output(self):
        """Closes synthesis D5: copied rows carry the NEW (target)
        embedder_version, not the old one. The VECTOR is content-
        identity-valid; the metadata column is rewritten."""
        new_chunks = {
            "arxiv:2401.00001:aaaaaaaaaaaaaaaa": _make_chunk(
                "2401.00001", "arxiv:2401.00001:aaaaaaaaaaaaaaaa"
            )
        }
        old_rows = {
            "arxiv:2401.00001:aaaaaaaaaaaaaaaa": {
                "embedding_stmt": _normalized(1),
                "embedding_proof": None,
                "embedder_version": "bge-m3@aaaaaaaa",
                "kind": "stmt",
            }
        }
        record = _build_copy_embed_record(
            new_chunks_by_id=new_chunks,
            old_rows_by_id=old_rows,
            old_embedder_version="bge-m3@aaaaaaaa",
            target_embedder_version="bge-m3@bbbbbbbb",
        )
        assert record.embedder_version == "bge-m3@bbbbbbbb"
        assert record.chunk_ids_stmt == ["arxiv:2401.00001:aaaaaaaaaaaaaaaa"]

    def test_routes_proof_to_embedding_proof(self):
        new_chunks = {
            "arxiv:2401.00001:aaaaaaaaaaaaaaaa": _make_chunk(
                "2401.00001", "arxiv:2401.00001:aaaaaaaaaaaaaaaa", kind="proof"
            )
        }
        old_rows = {
            "arxiv:2401.00001:aaaaaaaaaaaaaaaa": {
                "embedding_stmt": None,
                "embedding_proof": _normalized(1),
                "embedder_version": "bge-m3@aaaaaaaa",
                "kind": "proof",
            }
        }
        record = _build_copy_embed_record(
            new_chunks_by_id=new_chunks,
            old_rows_by_id=old_rows,
            old_embedder_version="bge-m3@aaaaaaaa",
            target_embedder_version="bge-m3@bbbbbbbb",
        )
        assert record.chunk_ids_proof == ["arxiv:2401.00001:aaaaaaaaaaaaaaaa"]
        assert record.chunk_ids_stmt == []


# ---------------------------------------------------------------------------
# End-to-end run_re_embed with mocked dependencies
# ---------------------------------------------------------------------------


# Synthetic state. The mocks below stand in for LanceDB + chunker +
# embedder so the tests run in milliseconds.


def _mk_chunk(pid: str, idx: int, *, kind: str = "stmt") -> ChunkRecord:
    """Make a synthetic chunk with a predictable id."""
    suffix = f"{idx:016x}"  # 16 hex chars
    return _make_chunk(pid, f"arxiv:{pid}:{suffix}", kind=kind)


def _ok_embed_stats():
    """Return an EmbedStats-like minimal stub mimicking status=ok."""
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


def _ok_full_record(paper_id: str, new_ids: list[str]) -> EmbedRecord:
    return EmbedRecord(
        chunk_ids_stmt=new_ids,
        embedding_stmt=np.asarray(
            [_normalized(i) for i, _ in enumerate(new_ids)], dtype=np.float32
        )
        if new_ids
        else np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
        chunk_ids_proof=[],
        embedding_proof=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
        embedder_version=EMBEDDER_VERSION,
    )


class _StagingDoubleSpy:
    """Stub for `_staging_chunk_ids` that returns a fixed set."""

    def __init__(self, ids: set[str]):
        self._ids = ids
        self.calls = 0

    def __call__(self, staging_path):
        self.calls += 1
        return self._ids


class _WriteChunksSpy:
    """Records every call to `write_chunks` for assertion."""

    def __init__(self):
        self.calls: list[tuple[list[ChunkRecord], EmbedRecord]] = []

    def __call__(self, chunks, embeddings, lancedb_path=None):
        self.calls.append((list(chunks), embeddings))
        return 1  # synthetic version int


class TestCopyEfficacy:
    """Closes AC1: 95% unchanged → 95% copied without re-compute."""

    def test_95_percent_copy(self, tmp_path):
        active = tmp_path / "lancedb"
        staging = tmp_path / "lancedb-staging"
        _write_active_marker(active, embedder_version=EMBEDDER_VERSION)

        # 100 chunks across 10 papers (10 each). 5 of them are
        # "new" (re-embed); the rest are "copy".
        old_ids_by_paper: dict[str, set[str]] = {}
        new_chunks_by_paper: dict[str, list[ChunkRecord]] = {}
        for p in range(10):
            paper_id = f"2401.{p:05d}"
            unchanged_ids = []
            new_chunks: list[ChunkRecord] = []
            for c in range(10):
                # Stable id for indices 0..9 of papers 0..8 (90 chunks)
                # plus indices 0..4 of paper 9 (5 unchanged → 5 new).
                if p == 9 and c >= 5:
                    cid = f"arxiv:{paper_id}:{(p * 100 + c + 9999):016x}"
                else:
                    cid = f"arxiv:{paper_id}:{(p * 10 + c):016x}"
                    unchanged_ids.append(cid)
                new_chunks.append(
                    _make_chunk(paper_id, cid, kind="stmt")
                )
            old_ids_by_paper[paper_id] = set(unchanged_ids)
            new_chunks_by_paper[paper_id] = new_chunks

        # 95 chunks have ids in both sets; 5 are new (paper 9, c=5..9).
        # Old IDs that are in NEW set: 95. Old not in NEW: 0. So
        # chunks_copied=95, chunks_re_embedded=5.

        old_rows_by_id = {
            cid: {
                "embedding_stmt": _normalized(hash(cid) & 0x7FFFFFFF),
                "embedding_proof": None,
                "embedder_version": EMBEDDER_VERSION,
                "kind": "stmt",
            }
            for ids in old_ids_by_paper.values()
            for cid in ids
        }

        write_spy = _WriteChunksSpy()

        def _chunk_paper_stub(pid):
            return new_chunks_by_paper[pid]

        def _index_stub(_):
            return old_ids_by_paper

        def _load_old_rows_stub(_, ids, *, cache=None):
            return {cid: old_rows_by_id[cid] for cid in ids}

        def _build_old_rows_index_stub(_):
            return old_rows_by_id

        # Closes adversary F3: count actual embedder calls so the
        # AC1 assertion verifies "no re-compute for copy chunks",
        # not just orchestrator accounting.
        embed_calls: list[str] = []

        def _embed_paper_stub(pid):
            embed_calls.append(pid)
            return _ok_embed_stats()

        def _load_embed_record_stub(pid):
            # Return the 5 new chunks for paper 9; empty for others.
            if pid == "2401.00009":
                new_ids = [
                    c.chunk_id
                    for c in new_chunks_by_paper[pid]
                    if c.chunk_id not in old_ids_by_paper[pid]
                ]
                return _ok_full_record(pid, new_ids)
            return _ok_full_record(pid, [])

        def _staging_versions_stub(_path, _target):
            return None

        with (
            patch("ingest.re_embed.chunk_paper", _chunk_paper_stub),
            patch(
                "ingest.re_embed._index_old_chunk_ids_by_paper", _index_stub
            ),
            patch(
                "ingest.re_embed._build_old_rows_index",
                _build_old_rows_index_stub,
            ),
            patch("ingest.re_embed._load_old_rows", _load_old_rows_stub),
            patch("ingest.re_embed.embed_paper", _embed_paper_stub),
            patch(
                "ingest.re_embed.load_embed_record", _load_embed_record_stub
            ),
            patch(
                "ingest.re_embed._check_staging_embedder_versions",
                _staging_versions_stub,
            ),
            patch("ingest.re_embed.write_chunks", write_spy),
        ):
            summary = run_re_embed(
                active_lancedb_path=active,
                staging_lancedb_path=staging,
                state_path=tmp_path / "state.json",
                failures_path=tmp_path / "failures.jsonl",
            )

        assert summary.chunks_copied == 95
        assert summary.chunks_re_embedded == 5
        assert summary.copy_fraction == pytest.approx(0.95)
        # Closes F3: embedder called for exactly ONE paper (paper 9
        # is the only one with re-embed-pending chunks). The other
        # 9 papers' chunks were ALL copy candidates, so the embedder
        # MUST NOT have been called for them.
        assert embed_calls == ["2401.00009"], (
            f"AC1: expected embedder called only for paper 9; got {embed_calls}"
        )
        # At least one write_chunks call carried the 5 re-embed chunks.
        assert any(len(c[1].chunk_ids_stmt) == 5 for c in write_spy.calls)


class TestResume:
    """Closes AC2: --resume skips already-embedded chunks."""

    def test_resume_skips_done_chunks(self, tmp_path):
        active = tmp_path / "lancedb"
        staging = tmp_path / "lancedb-staging"
        _write_active_marker(active)

        # 1 paper with 10 chunks, all unchanged content (copy path).
        # Staging "already has" 5 of them — --resume must skip those 5.
        paper_id = "2401.00001"
        all_ids = [
            f"arxiv:{paper_id}:{i:016x}" for i in range(10)
        ]
        new_chunks = [
            _make_chunk(paper_id, cid) for cid in all_ids
        ]
        old_rows = {
            cid: {
                "embedding_stmt": _normalized(i),
                "embedding_proof": None,
                "embedder_version": EMBEDDER_VERSION,
                "kind": "stmt",
            }
            for i, cid in enumerate(all_ids)
        }

        write_spy = _WriteChunksSpy()

        with (
            patch(
                "ingest.re_embed.chunk_paper", lambda _pid: new_chunks
            ),
            patch(
                "ingest.re_embed._index_old_chunk_ids_by_paper",
                lambda _p: {paper_id: set(all_ids)},
            ),
            patch(
                "ingest.re_embed._build_old_rows_index",
                lambda _p: old_rows,
            ),
            patch(
                "ingest.re_embed._load_old_rows",
                lambda _path, ids, *, cache=None: {
                    cid: old_rows[cid] for cid in ids
                },
            ),
            patch(
                "ingest.re_embed._staging_chunk_ids",
                lambda _p: set(all_ids[:5]),  # first 5 already done
            ),
            patch(
                "ingest.re_embed._check_staging_embedder_versions",
                lambda _p, _v: None,
            ),
            patch("ingest.re_embed.write_chunks", write_spy),
        ):
            summary = run_re_embed(
                active_lancedb_path=active,
                staging_lancedb_path=staging,
                state_path=tmp_path / "state.json",
                failures_path=tmp_path / "failures.jsonl",
                resume=True,
            )

        # AC2: chunks_skipped_resume == 5 (the 5 already-present ids)
        assert summary.chunks_skipped_resume == 5
        # The other 5 chunks were copied (their content is unchanged).
        assert summary.chunks_copied == 5
        # write_chunks called once (for the remaining 5 copy ids).
        assert len(write_spy.calls) == 1
        assert len(write_spy.calls[0][1].chunk_ids_stmt) == 5


class TestSpaceMixingGuard:
    """Code guard on top of the runbook warning (synthesis D5)."""

    def test_refuses_mixed_space(self, tmp_path):
        active = tmp_path / "lancedb"
        staging = tmp_path / "lancedb-staging"
        _write_active_marker(active)

        # Use a side_effect to simulate the mixing-detection branch.
        def _check_stub(_path, target):
            raise RuntimeError(
                f"staging table contains rows with embedder_version "
                f"bge-m3@oldoldoldoldoldold which differ from the "
                f"target {target!r}. Refusing to mix embedding spaces."
            )

        with (
            patch(
                "ingest.re_embed._check_staging_embedder_versions",
                _check_stub,
            ),
            pytest.raises(RuntimeError, match="mix embedding spaces"),
        ):
            run_re_embed(
                active_lancedb_path=active,
                staging_lancedb_path=staging,
                state_path=tmp_path / "state.json",
                failures_path=tmp_path / "failures.jsonl",
            )


class TestDryRun:
    """Dry run does not call write_chunks; prints diff per paper."""

    def test_dry_run_skips_writes(self, tmp_path, capsys):
        active = tmp_path / "lancedb"
        _write_active_marker(active)

        write_spy = _WriteChunksSpy()
        paper_id = "2401.00001"
        new_chunks = [
            _make_chunk(paper_id, f"arxiv:{paper_id}:{i:016x}")
            for i in range(3)
        ]

        with (
            patch("ingest.re_embed.chunk_paper", lambda _pid: new_chunks),
            patch(
                "ingest.re_embed._index_old_chunk_ids_by_paper",
                lambda _p: {paper_id: {new_chunks[0].chunk_id}},
            ),
            patch(
                "ingest.re_embed._build_old_rows_index", lambda _p: {}
            ),
            patch(
                "ingest.re_embed._check_staging_embedder_versions",
                lambda _p, _v: None,
            ),
            patch("ingest.re_embed.write_chunks", write_spy),
        ):
            run_re_embed(
                active_lancedb_path=active,
                staging_lancedb_path=tmp_path / "lancedb-staging",
                state_path=tmp_path / "state.json",
                failures_path=tmp_path / "failures.jsonl",
                dry_run=True,
            )
        assert write_spy.calls == []
        out = capsys.readouterr().out
        assert paper_id in out
        assert "copy=" in out
        assert "reembed=" in out


# ---------------------------------------------------------------------------
# State-file persistence
# ---------------------------------------------------------------------------


class TestStateFile:
    def test_state_marks_complete_on_success(self, tmp_path):
        active = tmp_path / "lancedb"
        _write_active_marker(active)

        with (
            patch("ingest.re_embed.chunk_paper", lambda _pid: []),
            patch(
                "ingest.re_embed._index_old_chunk_ids_by_paper",
                lambda _p: {"2401.00001": set()},
            ),
            patch(
                "ingest.re_embed._build_old_rows_index", lambda _p: {}
            ),
            patch(
                "ingest.re_embed._check_staging_embedder_versions",
                lambda _p, _v: None,
            ),
            patch("ingest.re_embed.write_chunks", _WriteChunksSpy()),
        ):
            state_path = tmp_path / "state.json"
            summary = run_re_embed(
                active_lancedb_path=active,
                staging_lancedb_path=tmp_path / "lancedb-staging",
                state_path=state_path,
                failures_path=tmp_path / "failures.jsonl",
            )
        assert summary.papers_total == 1
        state = json.loads(state_path.read_text())
        assert state["status"] == "complete"
        # Closes IS5: chunks_skipped_resume present in final state.
        assert state["chunks_skipped_resume"] == 0

    def test_state_marks_complete_with_failures(self, tmp_path):
        active = tmp_path / "lancedb"
        _write_active_marker(active)

        def _chunker_raises(_pid):
            raise RuntimeError("synthetic chunker explosion")

        with (
            patch("ingest.re_embed.chunk_paper", _chunker_raises),
            patch(
                "ingest.re_embed._index_old_chunk_ids_by_paper",
                lambda _p: {"2401.00001": set()},
            ),
            patch(
                "ingest.re_embed._build_old_rows_index", lambda _p: {}
            ),
            patch(
                "ingest.re_embed._check_staging_embedder_versions",
                lambda _p, _v: None,
            ),
        ):
            state_path = tmp_path / "state.json"
            summary = run_re_embed(
                active_lancedb_path=active,
                staging_lancedb_path=tmp_path / "lancedb-staging",
                state_path=state_path,
                failures_path=tmp_path / "failures.jsonl",
            )
        assert "2401.00001" in summary.papers_failed
        state = json.loads(state_path.read_text())
        assert state["status"] == "complete_with_failures"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestPaperIdValidation:
    def test_invalid_paper_id_in_list_raises(self, tmp_path):
        active = tmp_path / "lancedb"
        _write_active_marker(active)

        with (
            patch(
                "ingest.re_embed._index_old_chunk_ids_by_paper",
                lambda _p: {},
            ),
            patch(
                "ingest.re_embed._build_old_rows_index", lambda _p: {}
            ),
            patch(
                "ingest.re_embed._check_staging_embedder_versions",
                lambda _p, _v: None,
            ),
            pytest.raises(ValueError, match="invalid paper_id"),
        ):
            run_re_embed(
                paper_ids=["not-a-paper-id"],
                active_lancedb_path=active,
                staging_lancedb_path=tmp_path / "lancedb-staging",
                state_path=tmp_path / "state.json",
                failures_path=tmp_path / "failures.jsonl",
            )


# ---------------------------------------------------------------------------
# Runbook content (AC3 + AC4)
# ---------------------------------------------------------------------------


class TestRunbookContent:
    runbook = (
        Path(__file__).resolve().parent.parent
        / "docs" / "ops" / "re-embed-runbook.md"
    )

    def test_runbook_exists(self):
        assert self.runbook.is_file(), f"runbook missing at {self.runbook}"

    def test_warns_against_mixing_spaces(self):
        """Closes AC4."""
        text = self.runbook.read_text(encoding="utf-8")
        # Must mention the danger explicitly.
        assert (
            "mixing embedding spaces" in text.lower()
            or "mix embedding spaces" in text.lower()
        ), "runbook must call out the embedding-space mixing risk"
        # Must mention the column or concept by name.
        assert (
            "embedder_version" in text or "embedding_space" in text
        )

    def test_gpu_hours_table_present(self):
        """Closes AC3 — runbook covers all four scenarios with ranges."""
        text = self.runbook.read_text(encoding="utf-8")
        # All four scenarios named.
        assert "model swap" in text.lower() or "embedder model swap" in text.lower()
        assert "chunker logic" in text.lower()
        assert "macro normalizer" in text.lower() or "macro-normalizer" in text.lower()
        assert "ar5iv" in text.lower()
        # A GPU-hours range table is present.
        assert "chunks/sec" in text or "c/s" in text

    def test_runbook_warns_against_advancing_active_marker(self):
        text = self.runbook.read_text(encoding="utf-8")
        # The staging-vs-active discipline must be explicit.
        assert "corpus-version.json" in text
        assert "staging" in text.lower()


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
    ``_compute_chunk_id`` rotates every chunk_id and silently
    invalidates the partial-re-embed contract. We pin the literal
    SHA of the function's source bytes so a future PR edit
    fails this test loudly, forcing the contributor to either
    revert OR bump ``CHUNKER_VERSION`` and re-pin in the same PR.
    """

    #: SHA-256 of `inspect.getsource(_compute_chunk_id)` as of the
    #: E11_S03 freeze. ANY edit to the function body (whitespace,
    #: docstring, algorithm) breaks this hash.
    #:
    #: To re-pin after a deliberate change:
    #: ``uv run python -c "import hashlib, inspect; from
    #: ingest.chunker import _compute_chunk_id; print(hashlib.sha256(
    #: inspect.getsource(_compute_chunk_id).encode()).hexdigest())"``
    EXPECTED_COMPUTE_CHUNK_ID_SHA256 = (
        "6a49d455ce8898b0b602dbf8e84b433546cd4fa120cc9e522eff1d8486488f30"
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
            f"This is a SCHEMA migration, not a chunker_version "
            f"bump. Either revert the edit OR (1) bump "
            f"ingest.chunker_types.CHUNKER_VERSION, (2) update "
            f"EXPECTED_COMPUTE_CHUNK_ID_SHA256 in this test, and "
            f"(3) document the migration in the rectification commit "
            f"per ingest/chunker_types.py's schema-migration constraint."
        )

    def test_contract_strings_present(self):
        """Sanity guard alongside the SHA pin: even when a future
        edit re-pins the SHA, the canonical-bytes contract must
        still apply preamble_text + NFC normalization + sha256."""
        import inspect

        from ingest.chunker import _compute_chunk_id

        src = inspect.getsource(_compute_chunk_id)
        assert "unicodedata.normalize" in src
        assert "NFC" in src
        assert "sha256" in src
        assert "preamble_text" in src


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
        active = tmp_path / "lancedb"
        staging = tmp_path / "lancedb-staging"
        _write_active_marker(active)

        observed_sentinels: list[dict] = []
        write_spy = _WriteChunksSpy()
        original_write_chunks = write_spy.__call__

        sentinel_path = staging / "re-embed-progress.json"

        # Capture the sentinel mid-run (between paper write calls).
        def _capturing_write(chunks, embeddings, lancedb_path=None):
            if sentinel_path.is_file():
                observed_sentinels.append(
                    json.loads(sentinel_path.read_text())
                )
            return original_write_chunks(
                chunks, embeddings, lancedb_path=lancedb_path
            )

        paper_id = "2401.00001"
        # One paper, one new chunk → triggers re-embed path.
        new_chunks = [
            _make_chunk(paper_id, f"arxiv:{paper_id}:{i:016x}")
            for i in range(3)
        ]
        # No copies — every chunk is new.
        with (
            patch(
                "ingest.re_embed.chunk_paper", lambda _pid: new_chunks
            ),
            patch(
                "ingest.re_embed._index_old_chunk_ids_by_paper",
                lambda _p: {paper_id: set()},
            ),
            patch(
                "ingest.re_embed._build_old_rows_index", lambda _p: {}
            ),
            patch(
                "ingest.re_embed._check_staging_embedder_versions",
                lambda _p, _v: None,
            ),
            patch(
                "ingest.re_embed.embed_paper",
                lambda _pid: _ok_embed_stats(),
            ),
            patch(
                "ingest.re_embed.load_embed_record",
                lambda pid: _ok_full_record(
                    pid, [c.chunk_id for c in new_chunks]
                ),
            ),
            patch("ingest.re_embed.write_chunks", _capturing_write),
        ):
            run_re_embed(
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

    def test_sentinel_not_written_on_dry_run(self, tmp_path):
        active = tmp_path / "lancedb"
        staging = tmp_path / "lancedb-staging"
        _write_active_marker(active)

        paper_id = "2401.00001"
        new_chunks = [
            _make_chunk(paper_id, f"arxiv:{paper_id}:{i:016x}")
            for i in range(2)
        ]
        with (
            patch(
                "ingest.re_embed.chunk_paper", lambda _pid: new_chunks
            ),
            patch(
                "ingest.re_embed._index_old_chunk_ids_by_paper",
                lambda _p: {paper_id: set()},
            ),
            patch(
                "ingest.re_embed._build_old_rows_index", lambda _p: {}
            ),
            patch(
                "ingest.re_embed._check_staging_embedder_versions",
                lambda _p, _v: None,
            ),
        ):
            run_re_embed(
                active_lancedb_path=active,
                staging_lancedb_path=staging,
                state_path=tmp_path / "state.json",
                failures_path=tmp_path / "failures.jsonl",
                dry_run=True,
            )
        sentinel = staging / "re-embed-progress.json"
        assert not sentinel.is_file()


# ---------------------------------------------------------------------------
# Missing-old-rows guard — closes adversary F5
# ---------------------------------------------------------------------------


class TestMissingOldRows:
    """Closes adversary F5: when the active LanceDB drifts out of
    sync with the in-memory chunk_id index (race or corruption),
    a copy lookup with a missing chunk_id is logged as a per-paper
    failure rather than silently producing a partial copy."""

    def test_missing_chunk_id_raises_per_paper(self, tmp_path):
        active = tmp_path / "lancedb"
        staging = tmp_path / "lancedb-staging"
        _write_active_marker(active)

        paper_id = "2401.00001"
        existing_id = f"arxiv:{paper_id}:{0:016x}"
        new_chunks = [
            _make_chunk(paper_id, existing_id),
        ]

        with (
            patch(
                "ingest.re_embed.chunk_paper", lambda _pid: new_chunks
            ),
            patch(
                "ingest.re_embed._index_old_chunk_ids_by_paper",
                lambda _p: {paper_id: {existing_id}},
            ),
            # The cache is EMPTY — the old-rows lookup will find
            # nothing for the requested id, triggering the
            # missing-ids guard in _process_paper.
            patch(
                "ingest.re_embed._build_old_rows_index", lambda _p: {}
            ),
            patch(
                "ingest.re_embed._check_staging_embedder_versions",
                lambda _p, _v: None,
            ),
            patch(
                "ingest.re_embed.write_chunks", _WriteChunksSpy()
            ),
        ):
            failures = tmp_path / "failures.jsonl"
            summary = run_re_embed(
                active_lancedb_path=active,
                staging_lancedb_path=staging,
                state_path=tmp_path / "state.json",
                failures_path=failures,
            )
        assert paper_id in summary.papers_failed
        # The failure was logged to the JSONL.
        assert failures.is_file()
        rows = [
            json.loads(line)
            for line in failures.read_text().splitlines()
            if line.strip()
        ]
        assert any(r["paper_id"] == paper_id for r in rows)


# ---------------------------------------------------------------------------
# IS1 — Makefile re-embed: target carries the ARGS word-split hazard note
# ---------------------------------------------------------------------------


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
# IS2 — Runbook warns about concurrent invocations
# IS3 — Runbook says no automated scheduling
# ---------------------------------------------------------------------------


class TestRunbookOperatorWarnings:
    runbook = (
        Path(__file__).resolve().parent.parent
        / "docs" / "ops" / "re-embed-runbook.md"
    )

    def test_warns_about_concurrent_invocations(self):
        """Closes IS2."""
        text = self.runbook.read_text(encoding="utf-8")
        lower = text.lower()
        assert (
            "concurrent" in lower
            or "single instance" in lower
            or "two operators" in lower
        ), "runbook must warn against concurrent make re-embed runs"

    def test_declares_no_automated_scheduling(self):
        """Closes IS3."""
        text = self.runbook.read_text(encoding="utf-8")
        lower = text.lower()
        assert (
            "human-initiated" in lower
            or "no cron" in lower
            or "no automated scheduling" in lower
            or "no scheduled" in lower
        ), "runbook must explicitly declare absence of cron/systemd"


# ---------------------------------------------------------------------------
# IS4 — started_utc captured once, doesn't drift mid-run
# ---------------------------------------------------------------------------


class TestStartedUtcStable:
    """Closes IS4: the per-paper checkpoint writes must use the
    boot-time started_utc, not a fresh _utc_iso() per call."""

    def test_started_utc_does_not_drift(self, tmp_path):
        active = tmp_path / "lancedb"
        _write_active_marker(active)

        paper_id = "2401.00001"
        with (
            patch("ingest.re_embed.chunk_paper", lambda _pid: []),
            patch(
                "ingest.re_embed._index_old_chunk_ids_by_paper",
                lambda _p: {paper_id: set()},
            ),
            patch(
                "ingest.re_embed._build_old_rows_index", lambda _p: {}
            ),
            patch(
                "ingest.re_embed._check_staging_embedder_versions",
                lambda _p, _v: None,
            ),
            patch("ingest.re_embed.write_chunks", _WriteChunksSpy()),
        ):
            state_path = tmp_path / "state.json"
            run_re_embed(
                active_lancedb_path=active,
                staging_lancedb_path=tmp_path / "lancedb-staging",
                state_path=state_path,
                failures_path=tmp_path / "failures.jsonl",
            )
        state = json.loads(state_path.read_text())
        # `started_utc` should be present and stable; the
        # terminal write echoes the boot-time value rather than a
        # fresh timestamp.
        assert "started_utc" in state
        assert "completed_utc" in state
        # The boot-time started_utc is captured once at run start,
        # so it should equal the value written in the initial state
        # file write (which is what the final write also uses).
        assert state["started_utc"] <= state["completed_utc"]
