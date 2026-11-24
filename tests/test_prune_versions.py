"""The operator-run version prune keeps what readers pin and drops the rest."""

from __future__ import annotations

import json
import time
from datetime import timedelta

import lancedb
import numpy as np
import pytest

import arxmcp.ops.prune_versions as prune_mod
from arxmcp.corpus.chunk import CHUNKER_VERSION, EMBEDDING_DIM, ChunkRecord
from arxmcp.corpus.schema import CHUNKS_TABLE_NAME, EmbedRecord
from arxmcp.corpus.store import _build_arrow_table, write_chunks, write_corpus_version_marker
from arxmcp.ops.prune_versions import PruneRefused, _cli, plan_prune, prune_versions

#: Old versions are this much older than the ones the prune must keep.
_GAP_S = 1.2


@pytest.fixture(autouse=True)
def _short_slack(monkeypatch):
    # The production slack is minutes; these datasets are seconds old.
    monkeypatch.setattr(prune_mod, "_CUTOFF_SLACK", timedelta(seconds=0.5))


def _paper(pid: str) -> tuple[list[ChunkRecord], EmbedRecord]:
    chunks = [
        ChunkRecord(
            chunk_id=f"arxiv:{pid}:{i:016x}", paper_id=pid, kind="stmt",
            section_path=[], theorem_name=None, theorem_label=None,
            body_text=f"{pid} body {i}", body_tokens="body",
            chunker_version=CHUNKER_VERSION,
        )
        for i in range(2)
    ]
    rng = np.random.default_rng(int(pid[-1]))
    v = rng.standard_normal((len(chunks), EMBEDDING_DIM)).astype(np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    record = EmbedRecord(
        chunk_ids_stmt=[c.chunk_id for c in chunks], embedding_stmt=v,
        embedder_version="bge-m3@00000000",
    )
    return chunks, record


def _write(path, pid: str) -> int:
    chunks, record = _paper(pid)
    return write_chunks(chunks, record, lancedb_path=path, build_indices=False)


def _table(path):
    return lancedb.connect(str(path)).open_table(CHUNKS_TABLE_NAME)


def _versions(path) -> list[int]:
    return [int(v["version"]) for v in _table(path).list_versions()]


def _marker(path) -> dict:
    return json.loads((path / "corpus-version.json").read_text())


def _rows_at(path, version: int) -> int:
    tbl = _table(path)
    tbl.checkout(version)
    return tbl.count_rows()


@pytest.fixture
def dataset(tmp_path):
    """Two old papers, a gap, a paper, a gap, a paper the marker pins.

    The second gap puts the pin's predecessor outside the slack of the pin,
    so only the predecessor rule keeps it.
    """
    path = tmp_path / "lancedb"
    _write(path, "2401.00001")
    _write(path, "2401.00002")
    old = _versions(path)
    time.sleep(_GAP_S)
    _write(path, "2401.00003")
    time.sleep(_GAP_S)
    _write(path, "2401.00004")
    return path, old


class TestPrune:
    def test_removes_old_versions_and_keeps_the_pin(self, dataset):
        path, old = dataset
        marker = _marker(path)
        pinned = marker["version"]

        result = prune_versions(path, keep_days=0)

        remaining = _versions(path)
        assert set(old).isdisjoint(remaining)
        assert set(result.removed) >= set(old)
        assert {pinned - 1, pinned} <= set(remaining)
        # Readers and the corrupt-tip fallback both still open.
        assert _rows_at(path, pinned) == 8
        assert _rows_at(path, pinned - 1) == 6
        assert _marker(path) == marker

    def test_keeps_an_older_pin_and_its_predecessor(self, tmp_path):
        path = tmp_path / "lancedb"
        _write(path, "2401.00001")
        old = _versions(path)
        time.sleep(_GAP_S)
        _write(path, "2401.00002")
        _write(path, "2401.00003")
        pinned = _marker(path)["version"]
        time.sleep(_GAP_S)
        chunks, record = _paper("2401.00004")
        _table(path).add(_build_arrow_table(chunks, record))  # marker stays put
        assert max(_versions(path)) > pinned

        prune_versions(path, keep_days=0)

        remaining = _versions(path)
        assert {pinned - 1, pinned} <= set(remaining)
        assert set(old).isdisjoint(remaining)
        assert _rows_at(path, pinned) == 6

    def test_keep_days_keeps_recent_versions(self, dataset):
        path, _ = dataset
        before = _versions(path)
        result = prune_versions(path, keep_days=1)
        assert result.removed == ()
        assert _versions(path) == before

    def test_dry_run_changes_nothing(self, dataset, capsys):
        path, old = dataset
        before = _versions(path)
        assert _cli(["--lancedb-path", str(path), "--keep-days", "0", "--dry-run"]) == 0
        assert _versions(path) == before
        assert f"would remove {len(old)} version(s)" in capsys.readouterr().out
        assert set(plan_prune(path, keep_days=0).removable) == set(old)


class TestRefusals:
    def test_without_a_marker(self, dataset):
        path, _ = dataset
        (path / "corpus-version.json").unlink()
        with pytest.raises(PruneRefused, match="nothing names"):
            prune_versions(path, keep_days=0)

    def test_with_a_marker_naming_an_absent_version(self, dataset):
        path, _ = dataset
        write_corpus_version_marker(path, 9999, CHUNKER_VERSION, "bge-m3@x", 4, 8)
        before = _versions(path)
        assert _cli(["--lancedb-path", str(path), "--keep-days", "0"]) == 1
        assert _versions(path) == before

    def test_without_a_table(self, tmp_path):
        with pytest.raises(PruneRefused, match="no chunks table"):
            prune_versions(tmp_path / "lancedb")

    def test_negative_keep_days(self, dataset):
        path, _ = dataset
        with pytest.raises(ValueError):
            plan_prune(path, keep_days=-1)
